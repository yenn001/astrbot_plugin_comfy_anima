"""Runtime tool inventory with capability classification.

Names come from the 2.1.306 baseline runtime probe receipt
``tool_inventory_snapshot_20260828-143641.json`` (59 tools). Isolation uses
``drawing_request_allowlist()`` as the authoritative allow-list: unknown
tools and tools whose capability is delivery/relay/execution are removed
even when they are not on the blocked-name denylist.
"""

from __future__ import annotations

_CAP_ANIMA_ASSET = "anima_asset"
_CAP_ANIMA_ASSET_WRITE = "anima_asset_write"
_CAP_DANBOORU = "danbooru_lookup"
_CAP_DELIVERY = "delivery"
_CAP_EXECUTION = "execution"
_CAP_GROUP_QUERY = "group_query"
_CAP_MEMORY_READ = "memory_read"
_CAP_MEMORY_WRITE = "memory_write"
_CAP_MCP = "mcp_manage"
_CAP_SCHEDULE = "schedule"
_CAP_SKILL = "skill_manage"
_CAP_WEB = "web"

_DRAWING_REQUEST_ALLOWED_CAPABILITIES = frozenset(
    {
        _CAP_ANIMA_ASSET,
        _CAP_DANBOORU,
        _CAP_MEMORY_READ,
        _CAP_GROUP_QUERY,
    }
)

RUNTIME_TOOL_CAPABILITIES: dict[str, frozenset[str]] = {
    "add_mcp_server": frozenset({_CAP_MCP}),
    "astr_kb_search": frozenset({_CAP_MEMORY_READ}),
    "astrbot_execute_python": frozenset({_CAP_EXECUTION}),
    "astrbot_execute_shell": frozenset({_CAP_EXECUTION}),
    "astrbot_file_edit_tool": frozenset({_CAP_EXECUTION}),
    "astrbot_file_read_tool": frozenset({_CAP_EXECUTION}),
    "astrbot_file_write_tool": frozenset({_CAP_EXECUTION}),
    "astrbot_grep_tool": frozenset({_CAP_EXECUTION}),
    "astrbot_shell_session": frozenset({_CAP_EXECUTION}),
    "delete_skill": frozenset({_CAP_SKILL}),
    "disable_mcp_server": frozenset({_CAP_MCP}),
    "disable_skill": frozenset({_CAP_SKILL}),
    "enable_mcp_server": frozenset({_CAP_MCP}),
    "enable_skill": frozenset({_CAP_SKILL}),
    "future_task": frozenset({_CAP_SCHEDULE}),
    "get_mcp_server_config": frozenset({_CAP_MCP}),
    "install_skill": frozenset({_CAP_SKILL}),
    "list_anima_lora_presets": frozenset({_CAP_ANIMA_ASSET}),
    "list_anima_loras": frozenset({_CAP_ANIMA_ASSET}),
    "list_anima_prompt_plans": frozenset({_CAP_ANIMA_ASSET}),
    "list_mcp_servers": frozenset({_CAP_MCP}),
    "list_skills": frozenset({_CAP_SKILL}),
    "memorize_long_term_memory": frozenset({_CAP_MEMORY_WRITE}),
    "memory_companion_core_memory": frozenset({_CAP_MEMORY_READ}),
    "memory_companion_navigate": frozenset({_CAP_MEMORY_READ}),
    "memory_companion_note_create": frozenset({_CAP_MEMORY_WRITE}),
    "memory_companion_note_delete": frozenset({_CAP_MEMORY_WRITE}),
    "memory_companion_note_read": frozenset({_CAP_MEMORY_READ}),
    "memory_companion_recall": frozenset({_CAP_MEMORY_READ}),
    "memory_companion_remember": frozenset({_CAP_MEMORY_WRITE}),
    "pc_find_reaction_image": frozenset({_CAP_DELIVERY}),
    "pc_generate_photo": frozenset({_CAP_DELIVERY}),
    "pc_get_group_id_by_name": frozenset({_CAP_GROUP_QUERY}),
    "pc_get_specified_group_members": frozenset({_CAP_GROUP_QUERY}),
    "pc_get_user_id_by_name": frozenset({_CAP_GROUP_QUERY}),
    "pc_manage_memo": frozenset({_CAP_MEMORY_WRITE}),
    "pc_manage_schedule": frozenset({_CAP_SCHEDULE}),
    "pc_query_interaction": frozenset({_CAP_MEMORY_READ}),
    "pc_query_relation_person": frozenset({_CAP_MEMORY_READ}),
    "pc_qzone_publish_feed": frozenset({_CAP_DELIVERY}),
    "pc_qzone_reply_my_comment": frozenset({_CAP_DELIVERY}),
    "pc_qzone_view_feed": frozenset({_CAP_WEB}),
    "pc_relay_message": frozenset({_CAP_DELIVERY}),
    "pc_schedule_group_relay": frozenset({_CAP_DELIVERY}),
    "pc_send_current_media": frozenset({_CAP_DELIVERY}),
    "pc_send_to_group": frozenset({_CAP_DELIVERY}),
    "pc_send_to_groups": frozenset({_CAP_DELIVERY}),
    "pc_send_to_private_user": frozenset({_CAP_DELIVERY}),
    "pc_send_to_private_users": frozenset({_CAP_DELIVERY}),
    "pc_view_creative_work": frozenset({_CAP_WEB}),
    "recall_long_term_memory": frozenset({_CAP_MEMORY_READ}),
    "remove_mcp_server": frozenset({_CAP_MCP}),
    "save_anima_lora_style": frozenset({_CAP_ANIMA_ASSET_WRITE}),
    "search_anima_danbooru_tags": frozenset({_CAP_DANBOORU}),
    "send_message_to_user": frozenset({_CAP_DELIVERY}),
    "tavily_extract_web_page": frozenset({_CAP_WEB}),
    "update_mcp_server": frozenset({_CAP_MCP}),
    "update_skill_from_zip": frozenset({_CAP_SKILL}),
    "web_search_tavily": frozenset({_CAP_WEB}),
}

RUNTIME_TOOL_INVENTORY = frozenset(RUNTIME_TOOL_CAPABILITIES)


def capabilities_for_tool(name: str) -> frozenset[str]:
    """Return the classified capabilities for one inventory tool."""

    return RUNTIME_TOOL_CAPABILITIES.get(
        str(name or "").strip(), frozenset()
    )


def drawing_request_allowlist() -> tuple[str, ...]:
    """Return the capability-driven allow-list for a drawing request."""

    return tuple(
        sorted(
            name
            for name, capabilities in RUNTIME_TOOL_CAPABILITIES.items()
            if capabilities & _DRAWING_REQUEST_ALLOWED_CAPABILITIES
        )
    )


__all__ = [
    "RUNTIME_TOOL_CAPABILITIES",
    "RUNTIME_TOOL_INVENTORY",
    "capabilities_for_tool",
    "drawing_request_allowlist",
]
