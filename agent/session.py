import sys
from pathlib import Path

from agent import capabilities
from agent.mcp_client import MCPClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MeridianAgentSession:
    def __init__(self, elicitation_handler, sampling_handler, progress_handler, verbose=True):
        self.verbose = verbose
        self._tools_cache = None
        self._tools_dirty = True
        self.server_capabilities = {}

        self.client = MCPClient(
            server_cmd=[sys.executable, "-m", "mcp_server.server"],
            cwd=str(PROJECT_ROOT),
            elicitation_handler=elicitation_handler,
            sampling_handler=sampling_handler,
            progress_handler=progress_handler,
            notification_handler=self._on_notification,
        )

    # ---- Capability Negotiation -----------------------------------------
    def initialize(self):
        result = self.client.request(
            "initialize",
            {
                "protocolVersion": capabilities.PROTOCOL_VERSION,
                "capabilities": capabilities.CLIENT_CAPABILITIES,
                "clientInfo": capabilities.CLIENT_INFO,
            },
        )
        self.server_capabilities = result.get("capabilities", {})
        self.client.notify("notifications/initialized")

        if self.verbose:
            print("== initialize / initialized handshake ==")
            print(f"  client declared -> {capabilities.CLIENT_CAPABILITIES}")
            print(f"  server declared <- {self.server_capabilities}")
            print(f"  server info     <- {result.get('serverInfo')}")
        return result

    def server_supports(self, dotted_path: str) -> bool:
        """Dotted-path lookup into the server's declared capabilities,
        e.g. server_supports('tools.listChanged'). Called before the
        agent assumes a server-side promise is real, rather than just
        hoping."""
        node = self.server_capabilities
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return bool(node) if not isinstance(node, dict) else True

    # ---- Notifications ---------------------------------------------------
    def _on_notification(self, method, params):
        if method == "notifications/tools/list_changed":
            if self.verbose:
                print(
                    "\n  [notification] notifications/tools/list_changed received "
                    "— invalidating cached tool list"
                )
            self._tools_dirty = True
        elif self.verbose:
            print(f"\n  [notification] unhandled: {method} {params}")

    def tools_list(self, force=False):
        if self._tools_dirty or force or self._tools_cache is None:
            result = self.client.request("tools/list")
            self._tools_cache = result.get("tools", [])
            self._tools_dirty = False
        return self._tools_cache

    # ---- thin wrappers used by scenarios ----------------------------------
    def call_tool(self, name, arguments, progress_token=None):
        return self.client.call_tool(name, arguments, progress_token=progress_token)

    def authenticate(self, badge_code):
        return self.call_tool("authenticate", {"badge_code": badge_code})

    def list_resources(self):
        return self.client.request("resources/list")

    def read_resource(self, uri):
        return self.client.request("resources/read", {"uri": uri})

    def list_prompts(self):
        return self.client.request("prompts/list")

    def get_prompt(self, name, arguments=None):
        payload = {"name": name}
        if arguments:
            payload["arguments"] = arguments
        return self.client.request("prompts/get", payload)

    def close(self):
        self.client.close()
