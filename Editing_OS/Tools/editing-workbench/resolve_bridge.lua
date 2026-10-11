-- Editing-Pack Resolve bridge prototype v1: explicit read-only commands, no eval.
-- Start with dofile from Resolve's Lua Console. Default session limit: 30s.
-- PYTHONUTF8=1 and HF_HUB_DISABLE_SYMLINKS=1 apply to the Python client.
-- Lua does not launch Python or alter the process environment.
local app = rawget(_G, "resolve")
local native_ffi = rawget(_G, "ffi")
assert(app and native_ffi, "Resolve Console object and ffi are required")
local declarations = [[
void *fopen(const char *filename, const char *mode);
size_t fread(void *buffer, size_t size, size_t count, void *stream);
size_t fwrite(const void *buffer, size_t size, size_t count, void *stream);
int fclose(void *stream);
void Sleep(unsigned long milliseconds);
]]
native_ffi.cdef(declarations)
local crt = native_ffi.load("msvcrt")
local kernel = native_ffi.load("kernel32")
local root = assert(os.getenv("EDITING_PACK_RESOLVE_MAILBOX"), "Configure an external mailbox path")
root = root:gsub("\\", "/"):gsub("/+$", "") .. "/"
local request_path = root .. "resolve-lua-request.txt"
local response_path = root .. "resolve-lua-response.json"
local status_path = root .. "resolve-lua-status.json"
local function read_text(path)
    local file = crt.fopen(path, "rb")
    if file == nil then return nil end
    local buffer = native_ffi.new("char[65537]")
    local length = tonumber(crt.fread(buffer, 1, 65537, file))
    crt.fclose(file)
    assert(length <= 65536, "mailbox request exceeds limit")
    return native_ffi.string(buffer, length)
end
local function write_text(path, text)
    local file = crt.fopen(path, "wb")
    assert(file ~= nil, "mailbox output cannot be opened")
    local count = tonumber(crt.fwrite(text, 1, #text, file))
    crt.fclose(file)
    assert(count == #text, "mailbox short write")
end
local function quote(text)
    return '"' .. tostring(text):gsub('[%z\1-\31\\"]', function(c)
        return string.format("\\u%04x", string.byte(c))
    end) .. '"'
end
local function json(value, depth)
    depth = depth or 0
    assert(depth <= 8, "response depth exceeds limit")
    local kind = type(value)
    if value == nil then return "null" end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then
        assert(value == value and value ~= math.huge and value ~= -math.huge, "nonfinite number")
        return tostring(value)
    end
    if kind == "string" then return quote(value) end
    assert(kind == "table", "nonserializable response")
    local fields = {}
    for key, item in pairs(value) do
        assert(type(key) == "string", "response keys must be strings")
        fields[#fields + 1] = quote(key) .. ":" .. json(item, depth + 1)
    end
    table.sort(fields)
    return "{" .. table.concat(fields, ",") .. "}"
end
local function snapshot()
    local manager = app:GetProjectManager()
    assert(manager, "project manager unavailable")
    local project = manager:GetCurrentProject()
    local timeline = project and project:GetCurrentTimeline() or nil
    local result = {
        version = app:GetVersionString(), product = app:GetProductName(),
        project_name = project and project:GetName() or "",
        project_id = project and project:GetUniqueId() or "",
        timeline_count = project and project:GetTimelineCount() or 0,
        current_timeline = timeline and timeline:GetName() or "",
        read_only = true, transport = "editing-pack-lua-mailbox/v1"
    }
    if timeline then
        result.start_frame = timeline:GetStartFrame()
        result.end_frame = timeline:GetEndFrame()
    end
    return result
end
local function connection_test()
    local project = app:GetProjectManager():GetCurrentProject()
    assert(project and project:GetUniqueId() == assert(os.getenv("EDITING_PACK_RESOLVE_PROJECT_ID"), "Configure the verified project ID"),
        "connection test requires the verified project ID")
    assert(project:GetName() == assert(os.getenv("EDITING_PACK_RESOLVE_PROJECT_NAME"), "Configure the verified project name"), "connection test project name changed")
    assert(project:GetTimelineCount() == 0, "connection test requires zero existing timelines")
    local pool = project:GetMediaPool()
    assert(pool, "media pool unavailable")
    -- The native inventory confirms source/preview assets for this job are imported.
    -- This test never mutates or deletes media pool items or folders. Zero existing
    -- timelines and exact project identity constrain its isolated temporary edit.
    local timeline = pool:CreateEmptyTimeline("Editing-Pack bridge connection test")
    assert(timeline, "temporary timeline creation failed")
    local ok, result = pcall(function()
        assert(timeline:AddMarker(0, "Blue", "Editing-Pack was here", "Bridge write/readback test", 1,
            "editing-pack-connection-test"), "marker creation failed")
        local markers = timeline:GetMarkers()
        local marker = markers and markers[0]
        assert(marker and marker.name == "Editing-Pack was here" and marker.duration == 1,
            "marker readback mismatch")
        return {timeline_name=timeline:GetName(), marker_name=marker.name,
            marker_duration=marker.duration, marker_frame=0, readback_verified=true,
            project_id=project:GetUniqueId(), read_only=false}
    end)
    -- Cleanup uses only the exact newly-created timeline handle, including failures.
    local cleanup_ok, deleted = pcall(function() return pool:DeleteTimelines({timeline}) end)
    assert(cleanup_ok and deleted and project:GetTimelineCount() == 0,
        "temporary timeline cleanup failed; inspect project before continuing")
    if not ok then error(result) end
    result.cleanup_verified = true
    result.remaining_timeline_count = project:GetTimelineCount()
    return result
end
local function media_inventory()
    local project = app:GetProjectManager():GetCurrentProject()
    assert(project, "no current project")
    local root_folder = project:GetMediaPool():GetRootFolder()
    assert(root_folder, "no root folder")
    local result = {project_id=project:GetUniqueId(), project_name=project:GetName(),
        root_name=root_folder:GetName(), read_only=true}
    for _, label in ipairs({"clips", "folders"}) do
        local list
        if label == "clips" then list=root_folder:GetClipList() else list=root_folder:GetSubFolderList() end
        result[label .. "_type"] = type(list)
        local entries, count = {}, 0
        if type(list) == "table" then
            for key, value in pairs(list) do
                count = count + 1
                if count <= 16 then
                    local entry = {key=tostring(key), key_type=type(key), value_type=type(value)}
                    if type(value) == "string" or type(value) == "number" or type(value) == "boolean" then
                        entry.value = value
                    else
                        entry.description = tostring(value)
                        local ok, name = pcall(function() return value:GetName() end)
                        if ok and type(name) == "string" then entry.name=name end
                    end
                    entries["entry_" .. tostring(count)] = entry
                end
            end
        end
        result[label .. "_entries"] = entries
        result[label .. "_raw_key_count"] = count
    end
    return result
end
local started = os.time()
local session_id = tostring(bmd.createuuid())
local last_id = nil
-- Prevent a completed request being replayed when the Console script is restarted.
local previous = read_text(response_path)
if previous then last_id = previous:match('"id":"([%x]+)"') end
local function status(state)
    write_text(status_path, json({state=state, session_id=session_id,
        started_at=started, updated_at=os.time(), read_only=false,
        mutation_scope="guarded_connection_test",
        expires_at=started+30, transport="editing-pack-lua-mailbox/v1"}))
end
local function serve()
    status("ready")
    print("Editing-Pack Lua bridge ready: bounded to 30 seconds; guarded connection test available")
    while os.time() - started < 30 do
        local request = read_text(request_path)
        if request then
            local protocol, id, command, expires = request:match("^([%w_-]+)\n([%x]+)\n([%w_]+)\n(%d+)\n$")
            if protocol == "editingpack1" and id and #id == 32 and id ~= last_id then
                last_id = id
                local response = {id=id,session_id=session_id,completed_at=os.time(),ok=false}
                local close = command == "snapshot_once" or command == "stop" or command == "connection_test_once" or command == "media_inventory_once"
                local ok, value = pcall(function()
                    assert(tonumber(expires) >= os.time(), "request expired")
                    assert(tonumber(expires) <= os.time()+1800, "invalid request expiry")
                    if command == "snapshot" or command == "snapshot_once" then return snapshot() end
                    if command == "connection_test_once" then return connection_test() end
                    if command == "media_inventory_once" then return media_inventory() end
                    if command == "health" then return {read_only=true,version=app:GetVersionString()} end
                    if command == "capabilities" then
                        local fusion_app = app:Fusion()
                        return {fusion_app=tostring(fusion_app),
                            ui_manager_type=fusion_app and type(fusion_app.UIManager) or "nil",
                            ui_dispatcher_type=bmd and type(bmd.UIDispatcher) or "nil",
                            session_seconds=30,read_only=true}
                    end
                    if command == "stop" then return {stopped=true} end
                    error("unsupported read-only command")
                end)
                response.ok = ok
                if ok then response.result = value else response.error = tostring(value) end
                write_text(response_path, json(response))
                print("Editing-Pack request " .. command .. ": " .. (ok and "OK" or tostring(value)))
                if close then break end
            end
        end
        kernel.Sleep(50)
    end
    status("stopped")
    print("Editing-Pack Lua bridge stopped. Inspect the saved response for operation and cleanup evidence.")
end
local success, failure = pcall(serve)
if not success then
    pcall(status, "error")
    error(failure)
end
