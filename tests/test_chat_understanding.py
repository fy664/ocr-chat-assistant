"""Exercise whole-window recognition and the current Agent entry points."""
from __future__ import annotations

from io import BytesIO
import base64
import json

import numpy as np
from PIL import Image

from app.agent.conversation import ConversationAgent, ConversationRequest
from app.analysis.chat_layout import labeled_lines, recognize_chat_layout
from app.analysis.decoder import DecoderController
from app.llm.client import MOCK_RESULT
from app.models.schemas import ConversationInfo, OCRLine, OCRResult, RecentChatEvent
from app.ui.decoder_window import DecoderWindow
from tests.helpers import StubOCREngine, make_frame, wait_until
from tests.test_collection_pipeline import FakeSession, REGION


def line(text, x, y, width=80, height=15):
    return OCRLine(text=text, confidence=.99, box=[
        [x, y], [x + width, y], [x + width, y + height], [x, y + height],
    ])


def whole_window(*, group):
    image = np.full((520, 760, 3), 32, dtype=np.uint8)
    image[:, :245] = 48
    image[128:191, :245] = 78
    image[50, 245:] = 67
    image[420, 245:] = 67
    title = "项目讨论" if group else "小明"
    rows = [
        line("搜索", 45, 14), line("其他联系人", 59, 76),
        line("其他对话的预览", 59, 100), line(title, 59, 141),
        line("当前对话在左栏的预览", 59, 165), line("另一个群", 59, 210),
        line(title + " (10)" if group else title, 263, 17),
        line("输入框里的草稿", 265, 456),
    ]
    image[78:108, 264:294] = (208, 79, 122)
    if group:
        image[160:190, 264:294] = (100, 207, 140)
        rows += [
            line("LV58", 304, 78, 30, 11), line("小明", 338, 78, 28, 11),
            line("周一提交代码", 310, 101),
            line("小雨", 304, 160, 27, 11),
            line("我负责写说明", 310, 182),
        ]
    else:
        image[166:196, 708:738] = (104, 153, 225)
        rows += [line("周一有空吗？", 310, 83), line("有空", 646, 177, 45)]
    rows.sort(key=lambda row: (row.top, row.left))
    return image, OCRResult(lines=rows, raw_text="\n".join(row.text for row in rows), confidence=.99)


def test_whole_window_group_excludes_sidebar_and_composer():
    image, result = whole_window(group=True)
    observed = recognize_chat_layout(result, image)
    assert observed.conversation.kind == "group"
    assert observed.conversation.title == observed.conversation.sidebar_selected == "项目讨论"
    assert observed.chat_bounds is not None
    assert .31 < observed.chat_bounds[0] < .34
    assert "预览" not in observed.raw_text and "草稿" not in observed.raw_text
    assert [message for message in labeled_lines(observed.lines) if message] == [
        "小明：周一提交代码", "小雨：我负责写说明",
    ]
    assert len({row.chat.avatar for row in observed.lines if row.chat and row.chat.avatar}) == 2


def test_whole_window_private_uses_two_sided_evidence():
    image, result = whole_window(group=False)
    observed = recognize_chat_layout(result, image)
    assert observed.conversation.kind == "private"
    assert observed.conversation.tentative
    assert observed.conversation.title == "小明"
    assert [row.chat.side for row in observed.lines] == ["left", "right"]


def test_sparse_dialog_keeps_the_title_but_marks_the_type_unknown():
    image, result = whole_window(group=False)
    result.lines = [row for row in result.lines if row.text != "有空"]
    observed = recognize_chat_layout(result, image)
    assert observed.conversation.kind == "unknown"
    assert observed.chat_bounds is not None
    assert observed.conversation.title == "小明"
    assert [row.text for row in observed.lines] == ["周一有空吗？"]


def test_agent_uses_early_history_and_validates_recent_event_sources():
    class Client:
        def __init__(self):
            self.history_calls = []
            self.user = ""

        def summarize_history(self, system, payload):
            assert "忽略" in system
            self.history_calls.append(json.loads(payload))
            return "开头约定由小明负责，之后继续讨论"

        def analyze(self, system, context, images=None):
            assert "conversation_summary" in system and "recent_event" in system
            self.user = context
            result = MOCK_RESULT.model_copy(deep=True)
            result.recent_event = RecentChatEvent(
                topic="确认会议室", evidence_ids=["[M0042]", "M9999", "M0042"]
            )
            return result

    client = Client()
    text = "\n".join(["小明：期初约定"] + [f"消息{i}：" + ("讨论中间事项" * 20) for i in range(40)]
                     + ["小雨：最新事是确认会议室"])
    status = []
    result = ConversationAgent(client).run(
        ConversationRequest(text, 2000, False, conversation=ConversationInfo(title="项目讨论", kind="group")),
        on_status=status.append,
    )
    assert len(client.history_calls) > 1
    assert "期初约定" in client.history_calls[0]["messages"]
    assert "开头约定由小明负责" in client.history_calls[1]["previous_digest"]
    assert "开头约定由小明负责" in client.user and "最新事是确认会议室" in client.user
    assert "项目讨论" in client.user
    assert any(phase.startswith("history:") for phase in status)
    assert result.recent_event.evidence_ids == ["M0042"]
    assert result.event_sources == ["[M0042] 小雨：最新事是确认会议室"]


def test_auto_analysis_after_window_read(qapp, make_settings):
    image, result = whole_window(group=True)

    class Engine:
        def recognize(self, _image):
            return result

    settings = make_settings(vision_enabled=False)
    controller = DecoderController(settings, mock_llm=True, ocr_engine_factory=Engine)
    window = DecoderWindow(controller, settings)
    completed = []
    controller.analysis_completed.connect(completed.append)
    try:
        assert not window._auto_analysis.isChecked()
        window._auto_analysis.setChecked(True)
        controller.capture_from_image(image)
        assert wait_until(qapp, lambda: completed)
        assert "群聊" in window._conversation_label.text()
        assert "小雨：我负责写说明" in window._editor.toPlainText()
        assert completed[0].conversation_summary is not None
        assert completed[0].recent_event is not None
        assert completed[0].suggested_replies
    finally:
        window.close()
        controller.shutdown()


def test_switch_chat_never_merges_other_messages_or_attaches_its_image(qapp, make_settings):
    observed = iter([
        OCRResult(raw_text="原群消息", normalized_text="原群消息", lines=[OCRLine(text="原群消息")],
                  conversation=ConversationInfo(title="原群", kind="group")),
        OCRResult(raw_text="私聊消息", normalized_text="私聊消息", lines=[OCRLine(text="私聊消息")],
                  conversation=ConversationInfo(title="新联系人", kind="private")),
    ])

    class Engine:
        def recognize(self, _image):
            return next(observed)

    sessions = []
    controller = DecoderController(
        make_settings(vision_enabled=True),
        mock_llm=True,
        ocr_engine_factory=Engine,
        session_factory=lambda region: sessions.append(FakeSession(region)) or sessions[-1],
    )
    completed = []
    controller.collection_completed.connect(completed.append)
    try:
        assert controller.start_collection(REGION)
        for color in (25, 210):
            frame = make_frame().model_copy(update={"image": np.full((24, 24, 3), color, np.uint8)})
            sessions[0].frame_ready.emit(frame, 1)
        assert wait_until(qapp, lambda: completed)
        assert completed[0]["text"] == "原群消息"
        assert sessions[0].closed
        assert controller.image_count == 1
        jpeg = Image.open(BytesIO(base64.b64decode(controller.images[0].split(",", 1)[1])))
        assert jpeg.getpixel((0, 0))[0] < 50
    finally:
        controller.shutdown()


def test_final_page_when_scrolling_up_does_not_become_latest_message(qapp, make_settings):
    sessions = []
    engine = StubOCREngine(texts=[
        "今晚在新地址见面\n收到，已经确认",
        "下午先去取包裹\n记得带取件码",
        "早上出门时下雨了\n带了一把伞",
    ])
    controller = DecoderController(
        make_settings(vision_enabled=False),
        mock_llm=True,
        ocr_engine_factory=lambda: engine,
        session_factory=lambda region: sessions.append(FakeSession(region)) or sessions[-1],
    )
    completed = []
    controller.collection_completed.connect(completed.append)
    try:
        assert controller.start_collection(REGION)
        session = sessions[0]
        session.frame_ready.emit(make_frame(), 1)
        session.frame_ready.emit(make_frame(), -1)
        assert wait_until(qapp, lambda: controller.stitcher.page_count == 2)
        session.final = make_frame()
        controller.stop_collection()
        assert wait_until(qapp, lambda: completed)
        transcript = completed[0]["text"]
        assert transcript.index("早上") < transcript.index("下午") < transcript.index("今晚")
    finally:
        controller.shutdown()
