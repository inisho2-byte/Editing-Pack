-- Editing-Pack read-only Resolve capability probe. Run through Workspace > Console.
-- No project edits, network listener, subprocess, FFI calls or package installs.
-- Windows shell environment contract: PYTHONUTF8=1 HF_HUB_DISABLE_SYMLINKS=1.
-- This Lua-only script cannot export shell variables and never launches Python.
local report = {
    "Editing-Pack Resolve Lua capability probe v2",
    "Read-only; no project or timeline modifications",
    "Lua=" .. tostring(_VERSION),
    "time=" .. tostring(os and os.date and os.date("%Y-%m-%dT%H:%M:%S%z") or "unavailable")
}
local function record(key, value)
    local line = key .. "=" .. tostring(value):gsub("[\r\n]", " ")
    report[#report + 1] = line
    print(line)
end
local function read_method(object, method)
    if object == nil then record(method, "no object"); return nil end
    local ok, result = pcall(function() return object[method](object) end)
    record(method, ok and result or ("ERROR: " .. tostring(result)))
    return ok and result or nil
end
print(report[1])
local app = rawget(_G, "resolve")
record("injected_resolve", app ~= nil)
if app == nil and type(rawget(_G, "Resolve")) == "function" then
    local ok, result = pcall(Resolve)
    if ok then app = result end
    record("Resolve_constructor", ok and app ~= nil)
end
if app == nil and bmd and type(bmd.scriptapp) == "function" then
    local ok, result = pcall(bmd.scriptapp, "Resolve")
    if ok then app = result end
    record("bmd_scriptapp", ok and app ~= nil)
end
local version = read_method(app, "GetVersionString")
local product = read_method(app, "GetProductName")
local manager = read_method(app, "GetProjectManager")
local project = read_method(manager, "GetCurrentProject")
read_method(project, "GetName")
read_method(project, "GetTimelineCount")
local timeline = read_method(project, "GetCurrentTimeline")
read_method(timeline, "GetName")
read_method(timeline, "GetStartFrame")
read_method(timeline, "GetEndFrame")
record("api_root_readable", version ~= nil and product ~= nil and manager ~= nil)
for _, name in ipairs({"dofile", "loadfile", "require", "io", "ffi", "bit", "coroutine"}) do
    record("global_" .. name, type(rawget(_G, name)))
end
for _, name in ipairs({"readstring", "writestring", "readfile", "writefile", "fileexists", "wait", "createuuid"}) do
    record("bmd_" .. name, bmd and type(bmd[name]) or "nil")
end
record("fusion_UIManager", fusion and type(fusion.UIManager) or "nil")
record("bmd_UIDispatcher", bmd and type(bmd.UIDispatcher) or "nil")
record("fusion_OpenFile", fusion and type(fusion.OpenFile) or "nil")
record("FILE_MODE_READ", rawget(_G, "FILE_MODE_READ"))
record("FILE_MODE_WRITE", rawget(_G, "FILE_MODE_WRITE"))
local output = assert(os.getenv("EDITING_PACK_RESOLVE_MAILBOX"), "Configure an external mailbox path with trailing slash") .. "resolve-lua-probe.txt"
local content = table.concat(report, "\n") .. "\n"
local saved, err = false, "No writable text API"
if io and type(io.open) == "function" then
    saved, err = pcall(function()
        local file, open_error = io.open(output, "w")
        if not file then error(open_error) end
        file:write(content)
        file:close()
    end)
elseif fusion and rawget(_G, "FILE_MODE_WRITE") and rawget(_G, "FILE_MODE_READ") then
    saved, err = pcall(function()
        -- Documented Fusion OpenFile/IOClass methods. No serialization functions.
        local file = fusion:OpenFile(output, FILE_MODE_WRITE)
        if not file then error("OpenFile write failed") end
        for _, line in ipairs(report) do file:WriteLine(line) end
        file:Close()
        local reader = fusion:OpenFile(output, FILE_MODE_READ)
        if not reader then error("OpenFile read failed") end
        for _, expected in ipairs(report) do
            local actual = reader:ReadLine()
            if actual and actual:gsub("[\r\n]+$", "") == expected then
                -- verified line
            else
                reader:Close(); error("report readback mismatch")
            end
        end
        reader:Close()
    end)
end
record("report_write_verified", saved)
if saved then print("Report: " .. output) else print("Report write: " .. tostring(err)) end
print("Probe finished. No project changes were made.")
