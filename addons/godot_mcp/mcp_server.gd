@tool
extends Node
class_name MCPServer

## MCP Server for Godot Engine
## Implements HTTP server with JSON-RPC 2.0 protocol for MCP communication

# Tool imports - Core
const SceneTools = preload("res://addons/godot_mcp/tools/scene_tools.gd")
const NodeTools = preload("res://addons/godot_mcp/tools/node_tools.gd")
const ResourceTools = preload("res://addons/godot_mcp/tools/resource_tools.gd")
const ProjectTools = preload("res://addons/godot_mcp/tools/project_tools.gd")
const ScriptTools = preload("res://addons/godot_mcp/tools/script_tools.gd")
const EditorTools = preload("res://addons/godot_mcp/tools/editor_tools.gd")
const DebugTools = preload("res://addons/godot_mcp/tools/debug_tools.gd")
const FileSystemTools = preload("res://addons/godot_mcp/tools/filesystem_tools.gd")
const AnimationTools = preload("res://addons/godot_mcp/tools/animation_tools.gd")

# Tool imports - Visual
const MaterialTools = preload("res://addons/godot_mcp/tools/material_tools.gd")
const ShaderTools = preload("res://addons/godot_mcp/tools/shader_tools.gd")
const LightingTools = preload("res://addons/godot_mcp/tools/lighting_tools.gd")
const ParticleTools = preload("res://addons/godot_mcp/tools/particle_tools.gd")

# Tool imports - 2D
const TilemapTools = preload("res://addons/godot_mcp/tools/tilemap_tools.gd")
const GeometryTools = preload("res://addons/godot_mcp/tools/geometry_tools.gd")

# Tool imports - Gameplay
const PhysicsTools = preload("res://addons/godot_mcp/tools/physics_tools.gd")
const NavigationTools = preload("res://addons/godot_mcp/tools/navigation_tools.gd")
const AudioTools = preload("res://addons/godot_mcp/tools/audio_tools.gd")

# Tool imports - Utilities
const UITools = preload("res://addons/godot_mcp/tools/ui_tools.gd")
const SignalTools = preload("res://addons/godot_mcp/tools/signal_tools.gd")
const GroupTools = preload("res://addons/godot_mcp/tools/group_tools.gd")

signal server_started
signal server_stopped
signal client_connected
signal client_disconnected
signal request_received(method: String, params: Dictionary)

var _tcp_server: TCPServer
var _port: int = 3000
var _host: String = "127.0.0.1"
var _running: bool = false
var _debug_mode: bool = false
var _clients: Array[StreamPeerTCP] = []
var _pending_data: Dictionary = {}  # client -> PackedByteArray
var _client_last_activity: Dictionary = {}  # client -> Time.get_ticks_msec()

# Tool instances
var _tools: Dictionary = {}
var _tool_definitions: Array[Dictionary] = []
var _disabled_tools: Array = []  # List of disabled tool names

# MCP Protocol info
const MCP_VERSION = "2024-11-05"
const SERVER_NAME = "godot-mcp-server"
const SERVER_VERSION = "1.1.0"
const MAX_HEADER_BYTES := 65536
const MAX_BODY_BYTES := 4194304
const MAX_BUFFER_BYTES := MAX_HEADER_BYTES + MAX_BODY_BYTES
const MAX_CONNECTIONS := 16
const MAX_REQUESTS_PER_CLIENT_PER_FRAME := 16
const CLIENT_IDLE_TIMEOUT_MS := 30000


func _init() -> void:
	_tcp_server = TCPServer.new()


func _ready() -> void:
	if _tcp_server == null:
		_tcp_server = TCPServer.new()
	if _tools.is_empty():
		_register_tools()


func _process(_delta: float) -> void:
	if not _running:
		return

	# Accept new connections
	while _tcp_server.is_connection_available():
		var client = _tcp_server.take_connection()
		if client and _clients.size() < MAX_CONNECTIONS:
			_clients.append(client)
			_pending_data[client] = PackedByteArray()
			_client_last_activity[client] = Time.get_ticks_msec()
			_debug("Client connected (total: %d)" % _clients.size())
			client_connected.emit()
		elif client:
			_send_http_response(client, 503, {"error": "Connection limit reached"})
			client.disconnect_from_host()

	# Process existing clients
	var clients_to_remove: Array[StreamPeerTCP] = []
	for client in _clients:
		client.poll()
		var status = client.get_status()

		if status == StreamPeerTCP.STATUS_CONNECTED:
			var available = client.get_available_bytes()
			if available > 0:
				var data = client.get_data(available)
				if data[0] == OK:
					var pending: PackedByteArray = _pending_data.get(client, PackedByteArray())
					pending.append_array(data[1])
					_pending_data[client] = pending
					_client_last_activity[client] = Time.get_ticks_msec()
					_debug("Received %d bytes, pending: %d" % [available, pending.size()])
					if pending.size() > MAX_BUFFER_BYTES:
						_send_http_response(client, 413, {"error": "Request buffer exceeds limit"})
						clients_to_remove.append(client)
					else:
						var processed := 0
						while processed < MAX_REQUESTS_PER_CLIENT_PER_FRAME and _process_http_request(client):
							processed += 1
				else:
					_debug("Error receiving data: %s" % data[0])
					clients_to_remove.append(client)
			elif Time.get_ticks_msec() - int(_client_last_activity.get(client, 0)) > CLIENT_IDLE_TIMEOUT_MS:
				_send_http_response(client, 408, {"error": "Request timeout"})
				clients_to_remove.append(client)
		elif status == StreamPeerTCP.STATUS_ERROR or status == StreamPeerTCP.STATUS_NONE:
			clients_to_remove.append(client)
			_debug("Client status changed: %s" % status)

	# Remove disconnected clients
	for client in clients_to_remove:
		_remove_client(client)


func initialize(port: int, host: String, debug: bool) -> void:
	_port = port
	_host = host
	_debug_mode = debug


func start() -> bool:
	if _running:
		return true

	if _tcp_server == null:
		_tcp_server = TCPServer.new()
	if _tools.is_empty():
		_register_tools()

	var error = _tcp_server.listen(_port, _host)
	if error != OK:
		push_error("[MCP] Failed to start server on port %d: %s" % [_port, error_string(error)])
		return false

	_running = true
	print("[MCP] Server started on http://%s:%d/mcp" % [_host, _port])
	server_started.emit()
	return true


func stop() -> void:
	if not _running:
		return

	# Disconnect all clients
	for client in _clients:
		client.disconnect_from_host()
	_clients.clear()
	_pending_data.clear()
	_client_last_activity.clear()

	_tcp_server.stop()
	_running = false
	print("[MCP] Server stopped")
	server_stopped.emit()


func is_running() -> bool:
	return _running


func set_port(port: int) -> void:
	_port = port


func set_debug_mode(debug: bool) -> void:
	_debug_mode = debug


func get_connection_count() -> int:
	return _clients.size()


func set_disabled_tools(disabled: Array) -> void:
	_disabled_tools = disabled


func get_disabled_tools() -> Array:
	return _disabled_tools


func is_tool_enabled(tool_name: String) -> bool:
	return not (tool_name in _disabled_tools)


func get_tools_by_category() -> Dictionary:
	"""Returns tools organized by category for UI display"""
	var result: Dictionary = {}

	for category in _tools:
		var executor = _tools[category]
		var tools = executor.get_tools()
		result[category] = tools

	return result


func get_enabled_tools() -> Array[Dictionary]:
	"""Returns only enabled tool definitions"""
	var enabled: Array[Dictionary] = []

	for tool_def in _tool_definitions:
		if is_tool_enabled(tool_def["name"]):
			enabled.append(tool_def)

	return enabled


func _register_tools() -> void:
	_tools.clear()
	# Register all tool executors - Core
	_tools["scene"] = SceneTools.new()
	_tools["node"] = NodeTools.new()
	_tools["resource"] = ResourceTools.new()
	_tools["project"] = ProjectTools.new()
	_tools["script"] = ScriptTools.new()
	_tools["editor"] = EditorTools.new()
	_tools["debug"] = DebugTools.new()
	_tools["filesystem"] = FileSystemTools.new()
	_tools["animation"] = AnimationTools.new()

	# Register all tool executors - Visual
	_tools["material"] = MaterialTools.new()
	_tools["shader"] = ShaderTools.new()
	_tools["lighting"] = LightingTools.new()
	_tools["particle"] = ParticleTools.new()

	# Register all tool executors - 2D
	_tools["tilemap"] = TilemapTools.new()
	_tools["geometry"] = GeometryTools.new()

	# Register all tool executors - Gameplay
	_tools["physics"] = PhysicsTools.new()
	_tools["navigation"] = NavigationTools.new()
	_tools["audio"] = AudioTools.new()

	# Register all tool executors - Utilities
	_tools["ui"] = UITools.new()
	_tools["signal"] = SignalTools.new()
	_tools["group"] = GroupTools.new()

	# Collect all tool definitions
	_tool_definitions.clear()
	for category in _tools:
		var executor = _tools[category]
		var tools = executor.get_tools()
		for tool_def in tools:
			tool_def["name"] = "%s_%s" % [category, tool_def["name"]]
			_tool_definitions.append(tool_def)

	if _debug_mode:
		print("[MCP] Registered %d tools" % _tool_definitions.size())


func _debug(message: String) -> void:
	if _debug_mode:
		print("[MCP] %s" % message)


func _process_http_request(client: StreamPeerTCP) -> bool:
	var data: PackedByteArray = _pending_data.get(client, PackedByteArray())
	if data.is_empty():
		return false

	var header_end := _find_sequence(data, PackedByteArray([13, 10, 13, 10]))
	if header_end == -1:
		if data.size() > MAX_HEADER_BYTES:
			_send_http_response(client, 431, {"error": "Request headers exceed limit"})
			_remove_client(client)
		return false

	var parsed_headers := _parse_http_headers(data.slice(0, header_end).get_string_from_ascii())
	if parsed_headers.has("error"):
		_send_http_response(client, 400, {"error": parsed_headers["error"]})
		_remove_client(client)
		return false

	var headers: Dictionary = parsed_headers["headers"]
	var body_start := header_end + 4
	var body_bytes := PackedByteArray()
	var consumed := body_start
	var is_chunked := headers.has("transfer-encoding") and str(headers["transfer-encoding"]).to_lower().contains("chunked")

	if is_chunked:
		var decoded := _decode_chunked_body(data.slice(body_start))
		if decoded.has("error"):
			_send_http_response(client, 400, {"error": decoded["error"]})
			_remove_client(client)
			return false
		if not decoded.get("complete", false):
			return false
		body_bytes = decoded["body"]
		consumed += int(decoded["consumed"])
	else:
		var content_length := 0
		if headers.has("content-length"):
			var content_length_text := str(headers["content-length"])
			if not content_length_text.is_valid_int() or int(content_length_text) < 0:
				_send_http_response(client, 400, {"error": "Invalid Content-Length"})
				_remove_client(client)
				return false
			content_length = int(content_length_text)
		if content_length > MAX_BODY_BYTES:
			_send_http_response(client, 413, {"error": "Request body exceeds limit"})
			_remove_client(client)
			return false
		if data.size() - body_start < content_length:
			return false
		body_bytes = data.slice(body_start, body_start + content_length)
		consumed += content_length

	if body_bytes.size() > MAX_BODY_BYTES:
		_send_http_response(client, 413, {"error": "Request body exceeds limit"})
		_remove_client(client)
		return false

	_pending_data[client] = data.slice(consumed)
	_client_last_activity[client] = Time.get_ticks_msec()
	var method := str(headers["method"])
	var path := str(headers["path"])
	var response: Dictionary

	if method == "POST" and path == "/mcp":
		if not _is_valid_utf8(body_bytes):
			response = {"status": 400, "body": _create_json_rpc_error(-32700, "Request body is not valid UTF-8", null)}
		else:
			var rpc_response := _handle_mcp_request(body_bytes.get_string_from_utf8())
			if rpc_response.get("respond", true):
				response = {"status": 200, "body": rpc_response.get("body", rpc_response)}
			else:
				response = {"status": 202, "body": null}
	elif method == "GET" and path == "/health":
		response = {"status": 200, "body": _create_health_response()}
	elif method == "GET" and path == "/api/tools":
		response = {"status": 200, "body": _create_tools_list_response()}
	elif method == "OPTIONS":
		response = {"status": 204, "body": null}
	else:
		response = {"status": 404, "body": {"error": "Not found"}}

	_send_http_response(client, int(response["status"]), response.get("body"))
	_debug("%s %s -> %d" % [method, path, int(response["status"])])
	return true


func _decode_chunked_body(data: PackedByteArray) -> Dictionary:
	var result := PackedByteArray()
	var position := 0

	while true:
		var line_end := _find_crlf(data, position)
		if line_end == -1:
			return {"complete": false}
		var chunk_size := _parse_hex_size(data, position, line_end)
		if chunk_size < 0:
			return {"error": "Invalid chunk size"}
		position = line_end + 2

		if chunk_size == 0:
			if data.size() < position + 2:
				return {"complete": false}
			if data[position] == 13 and data[position + 1] == 10:
				return {"complete": true, "body": result, "consumed": position + 2}
			var trailer_end := _find_sequence(data, PackedByteArray([13, 10, 13, 10]), position)
			if trailer_end == -1:
				return {"complete": false}
			return {"complete": true, "body": result, "consumed": trailer_end + 4}

		if chunk_size > MAX_BODY_BYTES or result.size() + chunk_size > MAX_BODY_BYTES:
			return {"error": "Chunked body exceeds limit"}
		if data.size() < position + chunk_size + 2:
			return {"complete": false}
		if data[position + chunk_size] != 13 or data[position + chunk_size + 1] != 10:
			return {"error": "Chunk is missing trailing CRLF"}
		result.append_array(data.slice(position, position + chunk_size))
		position += chunk_size + 2
	return {"complete": false}


func _parse_hex_size(data: PackedByteArray, start: int, end: int) -> int:
	var value := 0
	var digits := 0
	var position := start
	while position < end and (data[position] == 32 or data[position] == 9):
		position += 1
	while position < end:
		var byte := int(data[position])
		if byte == 59 or byte == 32 or byte == 9:
			break
		var digit := -1
		if byte >= 48 and byte <= 57:
			digit = byte - 48
		elif byte >= 65 and byte <= 70:
			digit = byte - 55
		elif byte >= 97 and byte <= 102:
			digit = byte - 87
		else:
			return -1
		value = value * 16 + digit
		digits += 1
		if value > MAX_BODY_BYTES:
			return value
		position += 1
	return value if digits > 0 else -1


func _find_crlf(data: PackedByteArray, start: int = 0) -> int:
	for index in range(start, data.size() - 1):
		if data[index] == 13 and data[index + 1] == 10:
			return index
	return -1


func _find_sequence(data: PackedByteArray, sequence: PackedByteArray, start: int = 0) -> int:
	if sequence.is_empty() or data.size() < sequence.size():
		return -1
	for index in range(start, data.size() - sequence.size() + 1):
		var matches := true
		for offset in range(sequence.size()):
			if data[index + offset] != sequence[offset]:
				matches = false
				break
		if matches:
			return index
	return -1


func _is_valid_utf8(data: PackedByteArray) -> bool:
	var index := 0
	while index < data.size():
		var first := int(data[index])
		if first <= 0x7F:
			index += 1
			continue
		var continuation_count := 0
		var codepoint := 0
		if first >= 0xC2 and first <= 0xDF:
			continuation_count = 1
			codepoint = first & 0x1F
		elif first >= 0xE0 and first <= 0xEF:
			continuation_count = 2
			codepoint = first & 0x0F
		elif first >= 0xF0 and first <= 0xF4:
			continuation_count = 3
			codepoint = first & 0x07
		else:
			return false
		if index + continuation_count >= data.size():
			return false
		for offset in range(1, continuation_count + 1):
			var continuation := int(data[index + offset])
			if continuation < 0x80 or continuation > 0xBF:
				return false
			codepoint = (codepoint << 6) | (continuation & 0x3F)
		if codepoint > 0x10FFFF or (codepoint >= 0xD800 and codepoint <= 0xDFFF):
			return false
		if continuation_count == 2 and codepoint < 0x800:
			return false
		if continuation_count == 3 and codepoint < 0x10000:
			return false
		index += continuation_count + 1
	return true


func _remove_client(client: StreamPeerTCP) -> void:
	if client in _clients:
		client.disconnect_from_host()
		_clients.erase(client)
		_pending_data.erase(client)
		_client_last_activity.erase(client)
		_debug("Client disconnected")
		client_disconnected.emit()


func _parse_http_headers(header_section: String) -> Dictionary:
	var lines := header_section.split("\r\n")
	if lines.is_empty():
		return {"error": "Missing request line"}
	var request_line := lines[0].split(" ", false)
	if request_line.size() != 3 or not str(request_line[2]).begins_with("HTTP/"):
		return {"error": "Invalid HTTP request line"}

	var headers: Dictionary = {
		"method": str(request_line[0]).to_upper(),
		"path": str(request_line[1]),
		"version": str(request_line[2])
	}
	for index in range(1, lines.size()):
		var line := str(lines[index])
		var colon_position := line.find(":")
		if colon_position <= 0:
			return {"error": "Invalid HTTP header"}
		var key := line.substr(0, colon_position).strip_edges().to_lower()
		var value := line.substr(colon_position + 1).strip_edges()
		if key == "content-length" and headers.has(key) and headers[key] != value:
			return {"error": "Conflicting Content-Length headers"}
		headers[key] = value
	return {"headers": headers}


func _handle_mcp_request(body: String) -> Dictionary:
	var json := JSON.new()
	var error := json.parse(body)

	if error != OK:
		_debug("JSON parse error: %s" % json.get_error_message())
		return {"respond": true, "body": _create_json_rpc_error(-32700, "Parse error: %s" % json.get_error_message(), null)}

	var request = json.get_data()
	if not request is Dictionary:
		return {"respond": true, "body": _create_json_rpc_error(-32600, "Invalid Request", null)}
	if request.get("jsonrpc") != "2.0":
		return {"respond": true, "body": _create_json_rpc_error(-32600, "jsonrpc must be '2.0'", request.get("id"))}
	if not request.has("method") or not request["method"] is String or str(request["method"]).is_empty():
		return {"respond": true, "body": _create_json_rpc_error(-32600, "method must be a non-empty string", request.get("id"))}
	if request.has("params") and not request["params"] is Dictionary:
		return {"respond": true, "body": _create_json_rpc_error(-32602, "params must be an object", request.get("id"))}

	var method := str(request["method"])
	var params: Dictionary = request.get("params", {})
	var id = request.get("id")
	var is_notification: bool = not request.has("id")

	request_received.emit(method, params)
	var response: Dictionary

	match method:
		"initialize":
			response = _handle_initialize(params, id)
		"notifications/initialized", "initialized":
			response = _create_json_rpc_response({}, id)
		"tools/list":
			response = _handle_tools_list(params, id)
		"tools/call":
			response = _handle_tools_call(params, id)
		"ping":
			response = _create_json_rpc_response({}, id)
		_:
			response = _create_json_rpc_error(-32601, "Method not found: %s" % method, id)

	_debug("RPC %s%s" % [method, " (notification)" if is_notification else ""])
	if is_notification:
		return {"respond": false}
	return {"respond": true, "body": response}


func _handle_initialize(params: Dictionary, id) -> Dictionary:
	var result = {
		"protocolVersion": MCP_VERSION,
		"capabilities": {
			"tools": {
				"listChanged": false
			}
		},
		"serverInfo": {
			"name": SERVER_NAME,
			"version": SERVER_VERSION
		}
	}
	return _create_json_rpc_response(result, id)


func _handle_tools_list(_params: Dictionary, id) -> Dictionary:
	var tools_list: Array[Dictionary] = []

	for tool_def in _tool_definitions:
		# Only include enabled tools
		if is_tool_enabled(tool_def["name"]):
			tools_list.append({
				"name": tool_def["name"],
				"description": tool_def.get("description", ""),
				"inputSchema": tool_def.get("inputSchema", {
					"type": "object",
					"properties": {}
				})
			})

	return _create_json_rpc_response({"tools": tools_list}, id)


func _handle_tools_call(params: Dictionary, id) -> Dictionary:
	if not params.has("name") or not params["name"] is String or str(params["name"]).is_empty():
		return _create_json_rpc_error(-32602, "tools/call requires a non-empty string name", id)
	if params.has("arguments") and not params["arguments"] is Dictionary:
		return _create_json_rpc_error(-32602, "tools/call arguments must be an object", id)

	var tool_name := str(params["name"])
	var arguments: Dictionary = params.get("arguments", {})

	# Check if tool is enabled
	if not is_tool_enabled(tool_name):
		return _create_tool_response({"success": false, "error": "Tool '%s' is disabled" % tool_name}, id)

	# Parse tool name: category_toolname
	var parts = tool_name.split("_", true, 1)
	if parts.size() < 2:
		return _create_tool_response({"success": false, "error": "Invalid tool name format: %s" % tool_name}, id)

	var category = parts[0]
	var actual_tool_name = parts[1]

	_debug("Category: %s, Tool: %s" % [category, actual_tool_name])

	if not _tools.has(category):
		return _create_tool_response({"success": false, "error": "Unknown tool category: %s" % category}, id)

	var tool_definition := _find_tool_definition(tool_name)
	if tool_definition.is_empty():
		return _create_tool_response({"success": false, "error": "Unknown tool: %s" % tool_name}, id)
	var validation_error := _validate_schema(arguments, tool_definition.get("inputSchema", {}), "arguments")
	if not validation_error.is_empty():
		return _create_json_rpc_error(-32602, validation_error, id)

	var executor = _tools[category]
	var result: Dictionary = executor.execute(actual_tool_name, arguments)
	_debug("Tool %s success=%s" % [tool_name, result.get("success", false)])

	return _create_tool_response(result, id)


func _find_tool_definition(tool_name: String) -> Dictionary:
	for definition in _tool_definitions:
		if definition.get("name") == tool_name:
			return definition
	return {}


func _validate_schema(value, schema: Dictionary, path: String) -> String:
	if schema.is_empty():
		return ""
	var expected_type := str(schema.get("type", ""))
	if not expected_type.is_empty() and not _matches_json_type(value, expected_type):
		return "%s must be %s" % [path, expected_type]
	if schema.has("enum") and not value in schema["enum"]:
		return "%s must be one of %s" % [path, JSON.stringify(schema["enum"])]
	if expected_type == "object":
		var object_value: Dictionary = value
		for required_key in schema.get("required", []):
			if not object_value.has(required_key):
				return "%s.%s is required" % [path, required_key]
		var properties: Dictionary = schema.get("properties", {})
		for key in object_value:
			if properties.has(key):
				var child_error := _validate_schema(object_value[key], properties[key], "%s.%s" % [path, key])
				if not child_error.is_empty():
					return child_error
	elif expected_type == "array" and schema.has("items"):
		for index in range(value.size()):
			var item_error := _validate_schema(value[index], schema["items"], "%s[%d]" % [path, index])
			if not item_error.is_empty():
				return item_error
	return ""


func _matches_json_type(value, expected_type: String) -> bool:
	match expected_type:
		"object": return value is Dictionary
		"array": return value is Array
		"string": return value is String
		"boolean": return value is bool
		"number": return value is int or value is float
		"integer": return value is int or (value is float and is_equal_approx(value, round(value)))
		"null": return value == null
		_: return true


func _create_tool_response(result: Dictionary, id) -> Dictionary:
	var sanitized_result = _sanitize_for_json(result)
	var result_text = JSON.stringify(sanitized_result)

	if _debug_mode:
		print("[MCP] Tool response text length: %d" % result_text.length())

	return _create_json_rpc_response({
		"content": [{
			"type": "text",
			"text": result_text
		}],
		"isError": not result.get("success", false)
	}, id)


func _create_json_rpc_response(result, id) -> Dictionary:
	return {
		"jsonrpc": "2.0",
		"result": result,
		"id": id
	}


func _create_json_rpc_error(code: int, message: String, id) -> Dictionary:
	return {
		"jsonrpc": "2.0",
		"error": {
			"code": code,
			"message": message
		},
		"id": id
	}


func _create_health_response() -> Dictionary:
	return {
		"status": "ok",
		"server": SERVER_NAME,
		"version": SERVER_VERSION,
		"running": _running,
		"connections": _clients.size()
	}


func _create_tools_list_response() -> Dictionary:
	return {
		"tools": _tool_definitions
	}


func _send_http_response(client: StreamPeerTCP, status_code: int, data = null) -> void:
	var body_bytes := PackedByteArray()
	if data != null:
		body_bytes = JSON.stringify(_sanitize_for_json(data)).to_utf8_buffer()
	var status_texts = {
		200: "OK", 202: "Accepted", 204: "No Content", 400: "Bad Request",
		404: "Not Found", 408: "Request Timeout", 413: "Content Too Large",
		431: "Request Header Fields Too Large", 500: "Internal Server Error",
		503: "Service Unavailable"
	}
	var status_text: String = status_texts.get(status_code, "Error")

	var headers = "HTTP/1.1 %d %s\r\n" % [status_code, status_text]
	if data != null:
		headers += "Content-Type: application/json; charset=utf-8\r\n"
	headers += "Content-Length: %d\r\n" % body_bytes.size()
	headers += "Access-Control-Allow-Origin: *\r\n"
	headers += "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
	headers += "Access-Control-Allow-Headers: Content-Type, Accept, X-Requested-With, Authorization\r\n"
	headers += "Access-Control-Max-Age: 86400\r\n"
	headers += "Connection: keep-alive\r\n"
	headers += "\r\n"

	# Send headers and body
	var header_bytes = headers.to_utf8_buffer()
	var err1 = client.put_data(header_bytes)
	var err2 := OK
	if not body_bytes.is_empty():
		err2 = client.put_data(body_bytes)
	_debug("Response status=%d size=%d errors=(h:%s, b:%s)" % [status_code, body_bytes.size(), err1, err2])


func _sanitize_for_json(value):
	"""Recursively sanitize values to ensure valid JSON serialization"""
	match typeof(value):
		TYPE_DICTIONARY:
			var result = {}
			for key in value:
				# Ensure key is a string
				var str_key = str(key)
				result[str_key] = _sanitize_for_json(value[key])
			return result
		TYPE_ARRAY:
			var result = []
			for item in value:
				result.append(_sanitize_for_json(item))
			return result
		TYPE_FLOAT:
			# Handle NaN and Infinity which are not valid JSON
			if is_nan(value):
				return 0.0
			if is_inf(value):
				return 999999999.0 if value > 0 else -999999999.0
			return value
		TYPE_STRING:
			# Ensure string is valid
			return value
		TYPE_STRING_NAME:
			return str(value)
		TYPE_NODE_PATH:
			return str(value)
		TYPE_OBJECT:
			# Convert objects to string representation
			if value == null:
				return null
			return str(value)
		TYPE_VECTOR2, TYPE_VECTOR3, TYPE_VECTOR4:
			return str(value)
		TYPE_COLOR:
			return {"r": value.r, "g": value.g, "b": value.b, "a": value.a}
		TYPE_NIL:
			return null
		_:
			return value
