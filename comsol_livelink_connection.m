function status = comsol_livelink_connection(action)
% comsol_livelink_connection  Consulta o intenta conectar LiveLink con COMSOL.
%
% action:
%   'status'  -> solo consulta el estado actual de la sesion MATLAB
%   'connect' -> en Linux intenta conectar con mphstart y, si hace falta,
%                lanzar `comsol mphserver`; en Windows solo informa

    if nargin < 1 || isempty(action)
        action = 'status';
    end

    status = struct(...
        'connected', false, ...
        'platform', detect_platform(), ...
        'hasLiveLink', false, ...
        'canAutoConnect', false, ...
        'message', '', ...
        'detail', '', ...
        'version', '', ...
        'serverStartAttempted', false);

    status.hasLiveLink = has_livelink_functions();
    status.canAutoConnect = strcmp(status.platform, 'linux');

    if ~status.hasLiveLink
        status.message = ['LiveLink for MATLAB no esta disponible en esta sesion. ' ...
            'Abre MATLAB desde COMSOL o revisa la instalacion de LiveLink.'];
        return;
    end

    [connected, detail, versionText] = probe_connection();
    if connected
        status.connected = true;
        status.version = versionText;
        status.message = build_connected_message(versionText);
        return;
    end

    status.detail = detail;

    if strcmpi(action, 'connect') && strcmp(status.platform, 'linux')
        [connected, detail, versionText, startAttempted] = connect_on_linux();
        status.serverStartAttempted = startAttempted;
        status.connected = connected;
        status.detail = detail;
        status.version = versionText;

        if connected
            status.message = ['Servidor COMSOL conectado en Linux. ' ...
                build_connected_message(versionText)];
            return;
        end
    end

    status.message = build_disconnected_message(status.platform, status.serverStartAttempted);
end

function platform = detect_platform()
    if ispc
        platform = 'windows';
    elseif isunix && ~ismac
        platform = 'linux';
    elseif ismac
        platform = 'mac';
    else
        platform = 'unknown';
    end
end

function tf = has_livelink_functions()
    tf = exist('mphload', 'file') ~= 0 || ...
         exist('mphstart', 'file') ~= 0 || ...
         exist('mphversion', 'file') ~= 0;
end

function [connected, detail, versionText] = probe_connection()
    connected = false;
    detail = '';
    versionText = '';

    if exist('mphversion', 'file') ~= 0
        try
            versionValue = mphversion;
            versionText = normalize_value(versionValue);
            connected = true;
            return;
        catch err
            detail = err.message;
            if is_not_connected_error(err)
                return;
            end
        end
    end

    probeMethods = {@probe_modelutil_tags, @probe_modelutil_modeltags};
    for idx = 1:numel(probeMethods)
        try
            probeMethods{idx}();
            connected = true;
            return;
        catch err
            detail = err.message;
            if is_missing_method_error(err)
                continue;
            end
            if is_not_connected_error(err)
                return;
            end
        end
    end
end

function probe_modelutil_tags()
    com.comsol.model.util.ModelUtil.tags();
end

function probe_modelutil_modeltags()
    com.comsol.model.util.ModelUtil.modelTags();
end

function [connected, detail, versionText, startAttempted] = connect_on_linux()
    connected = false;
    detail = '';
    versionText = '';
    startAttempted = false;

    [connected, detail, versionText] = try_mphstart_retries(1, 0.0);
    if connected
        return;
    end

    if exist('mphstart', 'file') == 0
        detail = [detail ' | mphstart no esta disponible en esta sesion MATLAB.'];
        return;
    end

    startAttempted = true;
    [statusCode, output] = system(['bash -lc ''nohup comsol mphserver ' ...
        '> /tmp/comsol_mphserver.log 2>&1 &''']);

    if statusCode ~= 0
        detail = strtrim(output);
        return;
    end

    [connected, detail, versionText] = try_mphstart_retries(6, 2.0);
    if ~connected && isempty(strtrim(detail))
        detail = ['Se lanzo `comsol mphserver`, pero MATLAB no pudo conectar. ' ...
            'Revisa /tmp/comsol_mphserver.log y el puerto por defecto de COMSOL.'];
    end
end

function [connected, detail, versionText] = try_mphstart_retries(maxTries, pauseSeconds)
    connected = false;
    detail = '';
    versionText = '';

    for attempt = 1:maxTries
        try
            mphstart();
        catch err
            detail = err.message;
        end

        [connected, probeDetail, versionText] = probe_connection();
        if connected
            return;
        end

        if ~isempty(strtrim(probeDetail))
            detail = probeDetail;
        end

        if attempt < maxTries && pauseSeconds > 0
            pause(pauseSeconds);
        end
    end
end

function tf = is_not_connected_error(err)
    tf = false;
    if isempty(err)
        return;
    end

    msg = lower(err.message);
    tf = contains(msg, 'not connected to a server') || ...
         contains(msg, 'no conectado a un servidor') || ...
         contains(msg, 'connection refused') || ...
         contains(msg, 'failed to connect');
end

function tf = is_missing_method_error(err)
    msg = lower(err.message);
    tf = contains(msg, 'no appropriate method') || ...
         contains(msg, 'undefined function') || ...
         contains(msg, 'unrecognized method');
end

function out = normalize_value(value)
    if ischar(value)
        out = strtrim(value);
    elseif isstring(value)
        out = strtrim(char(value));
    else
        out = strtrim(char(string(value)));
    end
end

function msg = build_connected_message(versionText)
    if isempty(strtrim(versionText))
        msg = 'Sesion MATLAB conectada a COMSOL Server.';
    else
        msg = ['Sesion MATLAB conectada a COMSOL Server (' versionText ').'];
    end
end

function msg = build_disconnected_message(platform, startAttempted)
    switch platform
        case 'windows'
            msg = ['Sin conexion. En Windows abre COMSOL with MATLAB manualmente ' ...
                'y vuelve a pulsar "Check / Connect LiveLink".'];
        case 'linux'
            if startAttempted
                msg = ['Sin conexion tras intentar lanzar `comsol mphserver`. ' ...
                    'Revisa que COMSOL este en PATH y que el servidor arranque correctamente.'];
            else
                msg = ['Sin conexion. Pulsa "Check / Connect LiveLink" para intentar ' ...
                    'lanzar `comsol mphserver` y conectar MATLAB.'];
            end
        otherwise
            msg = 'Sin conexion al servidor COMSOL desde MATLAB.';
    end
end