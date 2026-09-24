"""OCR engine abstraction + PaddleOCR adapter.

PaddleOCR 2.x (`ocr.ocr`) and 3.x (`ocr.predict`) return different result
structures; this adapter normalizes both into OCRResult. The engine must be
created and used from a single worker thread (Paddle is not used
concurrently here, and model loading is slow so it happens off the GUI
thread).
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.models.schemas import OCRLine, OCRResult
from app.ocr.normalize import normalize_line, normalize_text
from app.ocr.preprocess import preprocess
from app.utils.time import now_ts

logger = logging.getLogger("ocr_chat.ocr")

DEFAULT_OCR_LANG = "ch"


def _patch_six_meta_path_importer() -> None:
    """Workaround for a six 1.17 + Python 3.12 incompatibility.

    When `six.moves` is first used (e.g. by PySide6's import chain), six
    registers a `_SixMetaPathImporter` in sys.meta_path whose find_spec
    returns a spec with origin=None. On Python 3.12,
    `importlib._bootstrap._module_repr_from_spec` assumes origin=None means
    a namespace loader and reads `loader._path` - which six's importer does
    not define - so repr()/inspect.getfile() on such a module raises
    AttributeError (observed: importing paddleocr after PySide6 fails inside
    the pandas import). Giving the class a `_path` attribute fixes repr
    without changing import behavior.
    """
    try:
        import six

        if not hasattr(six._SixMetaPathImporter, "_path"):
            six._SixMetaPathImporter._path = ()
    except Exception:
        pass


class OCREngine(Protocol):
    def recognize(self, image) -> OCRResult: ...


class OCREngineError(RuntimeError):
    pass


def _box_to_points(box) -> list[list[float]]:
    try:
        pts = [[float(p[0]), float(p[1])] for p in box]
        return pts
    except Exception:
        return []


def _build_result(texts, scores, polys, timestamp: float) -> OCRResult:
    lines: list[OCRLine] = []
    for i, text in enumerate(texts):
        text = str(text).strip()
        if not text:
            continue
        try:
            score = float(scores[i])
        except (IndexError, TypeError, ValueError):
            score = 0.0
        try:
            box = _box_to_points(polys[i])
        except (IndexError, TypeError):
            box = []
        lines.append(OCRLine(text=text, confidence=score, box=box))

    lines.sort(key=lambda ln: (ln.top, ln.left))
    raw_text = "\n".join(ln.text for ln in lines)
    confidences = [ln.confidence for ln in lines if ln.confidence]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OCRResult(
        raw_text=raw_text,
        normalized_text=normalize_text(raw_text),
        lines=lines,
        confidence=round(mean_conf, 4),
        boxes=[ln.box for ln in lines],
        timestamp=timestamp,
    )


class PaddleOCREngine:
    """PaddleOCR wrapper supporting both the 2.x and 3.x Python APIs."""

    def __init__(self, lang: str = DEFAULT_OCR_LANG, use_angle_cls: bool = True):
        _patch_six_meta_path_importer()  # must run before `import paddleocr`
        try:
            import paddleocr
        except ImportError as exc:
            raise OCREngineError(f"PaddleOCR 未安装: {exc}") from exc

        self._version = tuple(
            int(part) for part in paddleocr.__version__.split(".")[:2] if part.isdigit()
        ) or (0, 0)
        self._use_angle_cls = use_angle_cls
        try:
            if self._version >= (3, 0):
                from paddleocr import PaddleOCR

                self._ocr = PaddleOCR(
                    lang=lang,
                    use_textline_orientation=use_angle_cls,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    # paddlepaddle 3.3.1 + PP-OCRv6 under OneDNN hits
                    # "ConvertPirAttribute2RuntimeAttribute not support" in the
                    # PIR executor (onednn_instruction.cc); plain CPU mode is
                    # stable on Windows. Verified 2026-09 on Windows 11.
                    enable_mkldnn=False,
                )
            else:
                from paddleocr import PaddleOCR

                self._ocr = PaddleOCR(lang=lang, use_angle_cls=use_angle_cls, show_log=False)
        except TypeError:
            # signature drift between minor versions: retry with the
            # smallest common constructor
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(lang=lang)

    @property
    def ready(self) -> bool:
        return getattr(self, "_ocr", None) is not None

    def recognize(self, image) -> OCRResult:
        timestamp = now_ts()
        if not self.ready:
            raise OCREngineError("OCR engine is not initialized")

        img = preprocess(image)
        try:
            if self._version >= (3, 0):
                return self._recognize_v3(img, timestamp)
            return self._recognize_v2(img, timestamp)
        except OCREngineError:
            raise
        except Exception as exc:
            raise OCREngineError(f"OCR 识别失败: {exc}") from exc

    def _recognize_v2(self, img, timestamp: float) -> OCRResult:
        raw = self._ocr.ocr(img, cls=self._use_angle_cls)
        if not raw:
            return _build_result([], [], [], timestamp)
        page = raw[0] or []
        texts, scores, polys = [], [], []
        for item in page:
            try:
                box, (text, score) = item[0], item[1]
            except (IndexError, TypeError, ValueError):
                continue
            texts.append(text)
            scores.append(score)
            polys.append(box)
        return _build_result(texts, scores, polys, timestamp)

    def _recognize_v3(self, img, timestamp: float) -> OCRResult:
        raw = self._ocr.predict(img)
        if not raw:
            return _build_result([], [], [], timestamp)
        page = raw[0]
        if isinstance(page, dict):
            texts = list(page.get("rec_texts") or [])
            scores = list(page.get("rec_scores") or [])
            polys = list(page.get("rec_polys") or page.get("dt_polys") or [])
            return _build_result(texts, scores, polys, timestamp)
        # some 3.x builds return the legacy nested-list shape
        texts, scores, polys = [], [], []
        for item in page or []:
            try:
                box, (text, score) = item[0], item[1]
            except (IndexError, TypeError, ValueError):
                continue
            texts.append(text)
            scores.append(score)
            polys.append(box)
        return _build_result(texts, scores, polys, timestamp)


def build_engine(lang: str = DEFAULT_OCR_LANG, use_angle_cls: bool = True) -> OCREngine:
    return PaddleOCREngine(lang=lang, use_angle_cls=use_angle_cls)
