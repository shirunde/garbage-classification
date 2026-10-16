"""语音只作为分拣状态机的启动和停止入口，不实现闲聊。"""

START = "帮我分类"
PAUSE = "暂停"
STOP = "结束分类"

COMMANDS = {
    START: "start",
    PAUSE: "pause",
    STOP: "stop",
}


def parse_command(text):
    if text is None:
        return None
    return COMMANDS.get(text.strip())
