from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "name": "regenerate_plan",
        "description": "사용자 요청을 반영해 플랜을 다시 생성한다.",
        "parameters": {
            "type": "object",
            "properties": {"instructions": {"type": "string", "description": "수정 방향 자연어 지침"}},
            "required": ["instructions"],
        },
    },
    {
        "name": "confirm",
        "description": "사용자가 현재 플랜을 그대로 확정.",
        "parameters": {"type": "object", "properties": {}},
    },
]
