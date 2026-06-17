%% Time_domain_extraction_GUI.m
%
% PURPOSE:
%   Script-based MATLAB GUI for time-domain eddy-current extraction using the
%   COMSOL LiveLink API.  Connects to a running COMSOL server, loads a .mph
%   model, auto-detects studies and solution IDs, creates CutPoint3D datasets
%   for 7 canonical measurement locations (with optional spatial offsets), and
%   extracts time-domain Beddy (differential eddy-field) data.  Results are
%   written to structured .txt files organised in 7 sub-folders.
%
% REQUIREMENTS ADDRESSED: 14.1, 14.2, 14.3, 14.4
%
% USAGE:
%   Run this script from the MATLAB command window or editor.  The GUI window
%   opens automatically.  No function arguments are required.
%
% NOTES:
%   - The COMSOL mli directory path is configurable via the "COMSOL mli path"
%     field in the GUI.  The default value is the path used in
%     EDDY_CURRENT_B_EXTRACTOR.m.
%   - All solution IDs are resolved dynamically from the loaded model; none
%     are hardcoded in this file.
%   - Do NOT modify main_gui.py, EDDY_CURRENT_B_EXTRACTOR.m, or any file
%     under analysis/.
%
% SEE ALSO: mphstart, mphload, mpheval

%% -------------------------------------------------------------------------
%  CONFIGURABLE PATH — COMSOL mli directory
%  Change this variable if COMSOL is installed to a non-default location.
%  The value is used as the initial content of the "COMSOL mli path" field
%  in the GUI; the user can override it at runtime without editing this file.
% --------------------------------------------------------------------------
DEFAULT_COMSOL_MLI_PATH = get_default_comsol_mli_path();

%% -------------------------------------------------------------------------
%  Add COMSOL mli to the MATLAB path so LiveLink functions are available.
%  A fresh addpath call is executed here at script start; the GUI "Connect"
%  button will repeat this with whatever path the user has entered.
% --------------------------------------------------------------------------
if ~isempty(DEFAULT_COMSOL_MLI_PATH) && exist(DEFAULT_COMSOL_MLI_PATH, 'dir')
    addpath(DEFAULT_COMSOL_MLI_PATH);
    rehash;
elseif ~isempty(DEFAULT_COMSOL_MLI_PATH)
    warning('Time_domain_extraction_GUI:mliNotFound', ...
        'Default COMSOL mli directory not found: %s\n%s', ...
        DEFAULT_COMSOL_MLI_PATH, ...
        'Update DEFAULT_COMSOL_MLI_PATH or enter the correct path in the GUI.');
end

%% -------------------------------------------------------------------------
%  GUI entry point — build and display the figure window.
%  All logic below this point is implemented in local helper functions.
% --------------------------------------------------------------------------
build_gui(DEFAULT_COMSOL_MLI_PATH);

% ==========================================================================
%                        HELPER FUNCTIONS
% ==========================================================================

% --------------------------------------------------------------------------
function build_gui(default_mli_path)
% build_gui  Create the main uifigure window and wire all controls.
%
% PURPOSE:
%   Constructs the GUI layout using absolute pixel positions, initialises
%   control state, wires all callbacks, and stores shared application state
%   in the figure's UserData struct.
%
% INPUT ARGUMENTS:
%   default_mli_path  char  (dimensionless)
%       Default filesystem path to the COMSOL mli directory.
%
% OUTPUT ARGUMENTS:
%   (none – the figure is managed by MATLAB's graphics system)
%
% COMSOL API CONSTRAINTS:
%   None directly; COMSOL API calls happen in callback functions.
%
% REQUIREMENTS ADDRESSED: 1.1, 1.4, 1.5, 2.3, 2.4, 2.5, 3.1, 4.1, 4.2,
%   4.3, 5.1, 5.2, 5.3, 6.1, 9.1, 9.2, 12.1, 12.2, 12.5, 4.4
% --------------------------------------------------------------------------

    % ------------------------------------------------------------------
    %  Figure — spacious engineering-tool layout
    % ------------------------------------------------------------------
    fig = uifigure( ...
        'Name',     'Time-Domain COMSOL Extractor', ...
        'Position', [70 40 1000 860], ...
        'Color',    [0.94 0.95 0.97], ...
        'Resize',   'off');

    % ------------------------------------------------------------------
    %  Shared application state
    % ------------------------------------------------------------------
    app.model            = [];
    app.ref_sol_id       = '';
    app.comp_sol_id      = '';
    app.studies          = [];   % struct array: tag, label, sol_id
    app.cancel_requested = false;
    app.overwrite_policy = 'unset';
    app.outputFolder     = '';
    app.default_mli_path = default_mli_path;

    % Layout constants
    LW  = 960;   % usable width
    LX  = 20;    % left margin
    cardColor = [1.00 1.00 1.00];
    accentColor = [0.84 0.88 0.94];

    % ------------------------------------------------------------------
    %  Section 1 — LiveLink Connection  (compact, like the reference GUI)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'LIVELINK CONNECTION', ...
        'Position', [LX 815 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 755 LW 60], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    app.connectBtn = uibutton(fig, 'push', ...
        'Text',       'Check / Connect LiveLink', ...
        'FontWeight', 'bold', ...
        'BackgroundColor', [0.92 0.94 0.98], ...
        'Position',   [32 772 170 28]);

    app.connectionStatusTitleLabel = uilabel(fig, ...
        'Text',       'LiveLink connection status:', ...
        'Position',   [220 774 165 22], ...
        'FontWeight', 'bold', ...
        'FontColor',  [0.20 0.24 0.30]);

    app.connectionStatusLabel = uilabel(fig, ...
        'Text',       'Unknown', ...
        'Position',   [390 774 570 22], ...
        'FontWeight', 'bold', ...
        'FontColor',  [0.45 0.45 0.45]);

    % ------------------------------------------------------------------
    %  Section 2 — Model  (y 640 … 615)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Model', ...
        'Position', [LX 735 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 650 LW 80], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    uilabel(fig, 'Text', 'Model file:', ...
        'Position', [32 694 76 22], ...
        'FontWeight', 'bold');

    app.modelPathField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Editable', 'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [114 694 700 24]);

    app.browseModelBtn = uibutton(fig, 'push', ...
        'Text',     'Browse Model', ...
        'BackgroundColor', [0.92 0.94 0.98], ...
        'Position', [826 693 150 28]);

    app.refSolLabel = uilabel(fig, ...
        'Text',     'Reference solution: –', ...
        'Position', [32 662 700 22], ...
        'FontColor', [0.22 0.28 0.35]);

    % ------------------------------------------------------------------
    %  Section 3 — Study selection  (y 565 … 545)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Study Selection', ...
        'Position', [LX 625 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 560 LW 60], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    uilabel(fig, 'Text', 'Comparison study:', ...
        'Position', [32 579 130 22], ...
        'FontWeight', 'bold');

    app.studyDropdown = uidropdown(fig, ...
        'Items',    {}, ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [170 578 440 26]);

    % ------------------------------------------------------------------
    %  Section 4 — Analysis Type  (y 510 … 478)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Analysis Type', ...
        'Position', [LX 535 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 450 LW 80], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    uilabel(fig, 'Text', 'Analysis Type:', ...
        'Position', [32 486 100 22], ...
        'FontWeight', 'bold');

    app.analysisTypeGroup = uibuttongroup(fig, ...
        'BackgroundColor', cardColor, ...
        'Position',      [138 462 520 44], ...
        'BorderType',    'none');

    app.rbPoint = uiradiobutton(app.analysisTypeGroup, ...
        'Text',     'Point', ...
        'Tag',      'rbPoint', ...
        'Value',    true, ...
        'Position', [8 12 90 22], ...
        'FontSize', 12);

    app.rbCylinder = uiradiobutton(app.analysisTypeGroup, ...
        'Text',     'Cylinder', ...
        'Tag',      'rbCylinder', ...
        'Value',    false, ...
        'Position', [120 12 100 22], ...
        'FontSize', 12);

    app.radiusLabel = uilabel(fig, ...
        'Text',     'Radius (mm):', ...
        'Visible',  'off', ...
        'Position', [370 474 90 22], ...
        'FontWeight', 'bold');

    app.radiusField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Visible',  'off', ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [465 472 120 24]);

    app.heightLabel = uilabel(fig, ...
        'Text',     'Height (mm):', ...
        'Visible',  'off', ...
        'Position', [610 474 90 22], ...
        'FontWeight', 'bold');

    app.heightField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Visible',  'off', ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [705 472 120 24]);

    % ------------------------------------------------------------------
    %  Section 5 — Offset  (y 430 … 395)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Offset Configuration', ...
        'Position', [LX 437 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 330 LW 100], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    app.applyOffsetCheck = uicheckbox(fig, ...
        'Text',     'Apply Offset?', ...
        'Value',    false, ...
        'Position', [32 397 120 24], ...
        'FontWeight', 'bold');

    % Offset X
    uilabel(fig, 'Text', 'Offset X (mm):', ...
        'Position', [32 360 100 22], ...
        'FontWeight', 'bold');
    app.offsetXField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [138 360 180 24]);

    % Offset Y
    uilabel(fig, 'Text', 'Offset Y (mm):', ...
        'Position', [352 360 100 22], ...
        'FontWeight', 'bold');
    app.offsetYField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [458 360 180 24]);

    % Offset Z
    uilabel(fig, 'Text', 'Offset Z (mm):', ...
        'Position', [672 360 100 22], ...
        'FontWeight', 'bold');
    app.offsetZField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Enable',   'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [778 360 180 24]);

    % ------------------------------------------------------------------
    %  Section 6 — Time filter  (y 360 … 340)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Time Filter', ...
        'Position', [LX 315 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 255 LW 55], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    uilabel(fig, 'Text', 'Filter Time (ms):', ...
        'Position', [32 270 115 22], ...
        'FontWeight', 'bold');

    app.filterTimeField = uieditfield(fig, 'text', ...
        'Value',       '', ...
        'Placeholder', 'e.g. 100.4', ...
        'Enable',      'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position',    [152 269 220 24]);

    % ------------------------------------------------------------------
    %  Section 7 — Output folder  (y 290 … 270)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Output', ...
        'Position', [LX 240 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);
    uipanel(fig, ...
        'Position', [LX 175 LW 58], ...
        'BorderType', 'line', ...
        'BackgroundColor', cardColor);

    uilabel(fig, 'Text', 'Output folder:', ...
        'Position', [32 191 92 22], ...
        'FontWeight', 'bold');

    app.outputFolderField = uieditfield(fig, 'text', ...
        'Value',    '', ...
        'Editable', 'off', ...
        'BackgroundColor', [0.98 0.99 1.00], ...
        'Position', [132 190 680 24]);

    app.browseOutputBtn = uibutton(fig, 'push', ...
        'Text',     'Browse Output', ...
        'BackgroundColor', [0.92 0.94 0.98], ...
        'Position', [826 188 150 28]);

    % ------------------------------------------------------------------
    %  Section 8 — Log + progress  (y 10 … 268)
    % ------------------------------------------------------------------
    uilabel(fig, 'Text', 'Log', ...
        'Position', [LX 152 LW 20], ...
        'FontWeight', 'bold', ...
        'FontSize',   13, ...
        'FontColor',  [0.16 0.20 0.27]);

    app.logArea = uitextarea(fig, ...
        'Value',    {''}, ...
        'Editable', 'off', ...
        'BackgroundColor', [1.00 1.00 1.00], ...
        'Position', [LX 78 LW 70]);

    app.progressLabel = uilabel(fig, ...
        'Text',     'Ready.', ...
        'Position', [LX 28 260 24], ...
        'FontWeight', 'bold', ...
        'FontColor', [0.22 0.28 0.35]);

    app.extractBtn = uibutton(fig, 'push', ...
        'Text',     'Extract', ...
        'Enable',   'off', ...
        'FontWeight', 'bold', ...
        'FontSize', 14, ...
        'BackgroundColor', [0.12 0.45 0.82], ...
        'FontColor', [1 1 1], ...
        'Position', [360 20 220 42]);

    app.cancelBtn = uibutton(fig, 'push', ...
        'Text',     'Cancel', ...
        'Enable',   'off', ...
        'FontWeight', 'bold', ...
        'BackgroundColor', [0.88 0.91 0.95], ...
        'Position', [600 20 140 42]);

    % ------------------------------------------------------------------
    %  Store all handles in figure UserData
    % ------------------------------------------------------------------
    fig.UserData = app;

    % ==================================================================
    %  CALLBACKS (Tasks 2.2)
    % ==================================================================

    % ------------------------------------------------------------------
    %  5.2 / 5.3 — "Apply Offset?" checkbox toggles offset fields
    % ------------------------------------------------------------------
    app.applyOffsetCheck.ValueChangedFcn = @(src, ~) cb_toggle_offset(fig);

    % ------------------------------------------------------------------
    %  4.2 / 4.4 — Analysis Type radio group enable/disable Extract
    % ------------------------------------------------------------------
    app.analysisTypeGroup.SelectionChangedFcn = @(~, evt) cb_analysis_type(fig, evt);

    % ------------------------------------------------------------------
    %  1.5 / connect — "Connect" button
    % ------------------------------------------------------------------
    app.connectBtn.ButtonPushedFcn = @(~, ~) cb_connect(fig);

    % ------------------------------------------------------------------
    %  1.1 — "Browse Model" button
    % ------------------------------------------------------------------
    app.browseModelBtn.ButtonPushedFcn = @(~, ~) cb_browse_model(fig);

    % ------------------------------------------------------------------
    %  9.1 — "Browse Output" button
    % ------------------------------------------------------------------
    app.browseOutputBtn.ButtonPushedFcn = @(~, ~) cb_browse_output(fig);

    % ------------------------------------------------------------------
    %  12.1 / 12.5 — Extract + Cancel buttons
    % ------------------------------------------------------------------
    app.extractBtn.ButtonPushedFcn = @(~, ~) cb_extract(fig);
    app.cancelBtn.ButtonPushedFcn  = @(~, ~) cb_cancel(fig);

    % Re-store updated app struct (callbacks added after handle storage)
    fig.UserData = app;

    % Reflect the current LiveLink status immediately on startup.
    refresh_connection_indicator(fig, 'status', false);

end  % build_gui

% --------------------------------------------------------------------------
%  CALLBACK IMPLEMENTATIONS (nested in the same file, called by build_gui)
% --------------------------------------------------------------------------

% --- Req 5.2 / 5.3 --------------------------------------------------------
function cb_toggle_offset(fig)
% cb_toggle_offset  Toggle offset field enable state based on checkbox value.
    app = fig.UserData;
    tf = app.applyOffsetCheck.Value;  % true = checked
    if tf
        onOff = 'on';
    else
        onOff = 'off';
    end
    app.offsetXField.Enable = onOff;
    app.offsetYField.Enable = onOff;
    app.offsetZField.Enable = onOff;
end

% --- Req 4.2 / 4.4 --------------------------------------------------------
function cb_analysis_type(fig, evt)
% cb_analysis_type  Toggle analysis-type controls and Extract button state.
    app = fig.UserData;
    is_cylinder = strcmp(evt.NewValue.Tag, 'rbCylinder');

    if is_cylinder
        cyl_vis = 'on';
    else
        cyl_vis = 'off';
    end

    app.radiusLabel.Visible = cyl_vis;
    app.radiusField.Visible = cyl_vis;
    app.heightLabel.Visible = cyl_vis;
    app.heightField.Visible = cyl_vis;

    if ~isempty(app.model)
        app.radiusField.Enable = cyl_vis;
        app.heightField.Enable = cyl_vis;
        app.extractBtn.Enable = 'on';
    else
        app.extractBtn.Enable = 'off';
    end

    fig.UserData = app;
    figure(fig);   % devuelve el foco a la ventana GUI tras cambiar la selección
end

% --- Req 1.5 / connect -----------------------------------------------------
function cb_connect(fig)
% cb_connect  Ensure LiveLink helpers are on path and attempt connection.
%
%   1. Adds the default mli path if it exists and is not already on path.
%   2. Calls comsol_livelink_connection('connect').
%   3. Appends status.message to logArea.
    app = fig.UserData;

    ensure_comsol_mli_on_path(app.default_mli_path, app.logArea);

    refresh_connection_indicator(fig, 'connect', true);
end

% --------------------------------------------------------------------------
function status = refresh_connection_indicator(fig, action, should_log)
% refresh_connection_indicator  Query LiveLink and update visible GUI status.
    if nargin < 2 || isempty(action)
        action = 'status';
    end
    if nargin < 3
        should_log = false;
    end

    app = fig.UserData;
    status = comsol_livelink_connection(action);

    if status.connected
        app.connectionStatusLabel.Text = ['Connected - ' status.message];
        app.connectionStatusLabel.FontColor = [0.00 0.45 0.20];
        app.progressLabel.Text = 'LiveLink connected.';
        app.connectBtn.Text = 'Connected';
    else
        app.connectionStatusLabel.Text = ['Disconnected - ' status.message];
        app.connectionStatusLabel.FontColor = [0.75 0.10 0.10];
        app.progressLabel.Text = 'LiveLink disconnected.';
        app.connectBtn.Text = 'Connect';
    end

    fig.UserData = app;

    if should_log
        gui_log(app.logArea, status.message);
        if ~status.connected && ~isempty(strtrim(status.detail))
            gui_log(app.logArea, ['Detail: ' status.detail]);
        end
    end
end

% --------------------------------------------------------------------------
function default_mli_path = get_default_comsol_mli_path()
% get_default_comsol_mli_path  Choose a platform-appropriate initial mli path.
    if ispc
        default_mli_path = '';
    else
        default_mli_path = '/home/Comsol/Comsol/comsol64/multiphysics/mli';
    end
end

% --------------------------------------------------------------------------
function ensure_comsol_mli_on_path(default_mli_path, logArea)
% ensure_comsol_mli_on_path  Add the default mli folder quietly when present.
    if isempty(default_mli_path) || ~exist(default_mli_path, 'dir')
        return;
    end

    path_parts = strsplit(path, pathsep);
    if any(strcmp(path_parts, default_mli_path))
        return;
    end

    addpath(default_mli_path);
    rehash;

    if nargin >= 2 && ~isempty(logArea)
        gui_log(logArea, ['INFO: COMSOL mli path added: ' default_mli_path]);
    end
end

% --- Req 1.1 / 1.2 / 1.3 / 1.4 -------------------------------------------
function cb_browse_model(fig)
% cb_browse_model  Open file browser for .mph; load model; call after_model_load.
    app = fig.UserData;

    [fname, fpath] = uigetfile('*.mph', 'Select COMSOL model file');
    if isequal(fname, 0)
        return;  % user cancelled
    end

    fullpath = fullfile(fpath, fname);

    model = load_model(fullpath, fig);
    if isempty(model)
        return;  % load_model already showed error dialog
    end

    app.model = model;
    app.modelPathField.Value = fullpath;
    fig.UserData = app;

    after_model_load(fig);
end

% --- Req 9.1 / 9.2 --------------------------------------------------------
function cb_browse_output(fig)
% cb_browse_output  Open folder browser; store path; update display field.
    app = fig.UserData;

    folder = uigetdir('', 'Select output folder');
    if isequal(folder, 0)
        return;  % user cancelled
    end

    app.outputFolder = folder;
    app.outputFolderField.Value = folder;
    fig.UserData = app;
end

% --------------------------------------------------------------------------
%  UTILITY
% --------------------------------------------------------------------------
function gui_log(logArea, msg)
% gui_log  Append a line to the scrollable log text area.
    if isempty(msg)
        return;
    end
    current = logArea.Value;
    if ischar(current)
        current = {current};
    end
    % Remove placeholder empty line at the top if present
    if numel(current) == 1 && isempty(strtrim(strjoin(current, '')))
        current = {};
    end
    logArea.Value = [current; {msg}];
    scroll(logArea, 'bottom');
end

% --------------------------------------------------------------------------
function ui_errordlg(fig, message, title)
% ui_errordlg  Show an error dialog for uifigure-based GUI callbacks.
    if nargin < 3 || isempty(title)
        title = 'Error';
    end
    if nargin >= 1 && ~isempty(fig) && isvalid(fig)
        uialert(fig, message, title, 'Icon', 'error');
    else
        errordlg(message, title);
    end
end

% --------------------------------------------------------------------------
function model_out = load_model(model_path, fig)
% load_model  Load a .mph COMSOL model via the LiveLink API.
%
% PURPOSE:
%   Attempts to load the specified .mph model file using mphload.  The
%   COMSOL LiveLink server connection is expected to already be active
%   (established by the "Connect" button / cb_connect).  If mphload fails
%   because the server is not connected, a specific message instructs the
%   user to press "Connect" first.  All other mphload errors are displayed
%   via ui_errordlg with the raw MATLAB error message.
%
%   NOTE: mphstart is NOT called here.  Server startup / connection is the
%   sole responsibility of cb_connect / comsol_livelink_connection.
%
% INPUT ARGUMENTS:
%   model_path  char  (dimensionless — filesystem path)
%       Absolute or relative path to the .mph COMSOL model file to load.
%
% OUTPUT ARGUMENTS:
%   model_out   com.comsol.model.impl.ModelImpl  (dimensionless — Java object)
%       Live COMSOL model handle as returned by mphload.
%       Returns [] if the load fails for any reason.
%
% COMSOL API CONSTRAINTS:
%   - mphload raises a Java exception (wrapped by MATLAB) if the file is
%     missing, corrupt, or incompatible with the connected server version.
%   - mphload raises a "not connected" / "connection refused" error when no
%     COMSOL server is reachable; this case is surfaced with a targeted
%     message telling the user to press "Connect" first.
%   - The returned model handle is stateful; concurrent calls with different
%     paths will overwrite the previous model in the COMSOL server session.
%
% REQUIREMENTS ADDRESSED: 1.2, 1.3, 1.4, 1.5
% --------------------------------------------------------------------------

    model_out = [];

    try
        model_out = mphload(model_path);
    catch err
        % Check whether the failure is a connectivity problem so we can
        % give a more actionable message (Req 1.5 / 1.3).
        msg_lower = lower(err.message);
        if contains(msg_lower, 'not connected') || ...
                contains(msg_lower, 'connection refused')
            ui_errordlg(fig, ...
                ['COMSOL server is not connected. ' ...
                 'Please press "Connect" first, then try loading the model again.' ...
                 newline newline 'Detail: ' err.message], ...
                'Model Load Error');
        else
            ui_errordlg(fig, err.message, 'Model Load Error');
        end
        model_out = [];
    end

end

% --------------------------------------------------------------------------
function studies = detect_studies(model)
% detect_studies  Enumerate all study nodes in the loaded COMSOL model.
%
% PURPOSE:
%   Iterates over model.study.tags to collect every study's tag, its
%   human-readable label, and its associated solver solution ID.  The
%   solution ID is resolved dynamically via resolve_sol_id; no ID is ever
%   hardcoded.
%
% INPUT ARGUMENTS:
%   model  com.comsol.model.impl.ModelImpl  (dimensionless — Java object)
%       Live COMSOL model handle as returned by mphload.
%
% OUTPUT ARGUMENTS:
%   studies  struct array  (dimensionless)
%       Each element has three fields:
%           .tag     char   COMSOL study tag (e.g., 'std1').
%           .label   char   Human-readable study label (e.g., 'Reference').
%           .sol_id  char   Resolved solution tag (e.g., 'sol1').
%       Returns an empty struct array if no studies exist in the model.
%
% COMSOL API CONSTRAINTS:
%   - model.study.tags returns a Java StringArray; wrap with cell() before
%     iterating in MATLAB (Requirement 2.1).
%   - model.study('<tag>').label returns a Java String; wrap with char().
%   - Solver resolution depends on model.sol.tags and study feature
%     inspection; see resolve_sol_id for the full cross-referencing logic
%     (Requirement 2.2).
% --------------------------------------------------------------------------

    studies = struct('tag', {}, 'label', {}, 'sol_id', {});

    try
        study_tags = cell(model.study.tags);
        for i = 1:numel(study_tags)
            tag   = char(study_tags{i});
            label = char(model.study(tag).label);
            sol   = resolve_sol_id(model, tag);
            studies(end+1).tag   = tag;   %#ok<AGROW>
            studies(end).label   = label;
            studies(end).sol_id  = sol;
        end
    catch err
        warning('Time_domain_extraction_GUI:detectStudiesFailed', ...
            'detect_studies failed: %s', err.message);
        studies = struct('tag', {}, 'label', {}, 'sol_id', {});
    end

end

% --------------------------------------------------------------------------
function datasets = create_point_datasets(model, comp_sol_id)
% create_point_datasets  Create or reuse CutPoint3D datasets for all 7
%                        canonical measurement locations.
%
% PURPOSE:
%   For each of the 7 canonical Measurement_Locations (Center, ±X, ±Y, ±Z)
%   checks whether a CutPoint3D dataset with the expected tag already exists
%   in the model.  Creates the dataset if absent; reuses it if present.
%   Assigns the given Comparison_Study solution ID to each dataset and sets
%   the x/y/z coordinates in metres.
%
% INPUT ARGUMENTS:
%   model        com.comsol.model.impl.ModelImpl  (dimensionless — Java object)
%       Live COMSOL model handle.
%   comp_sol_id  char  (dimensionless)
%       Solution tag of the selected Comparison_Study (e.g., 'sol6').
%       Resolved dynamically from the model; never hardcoded.
%
% OUTPUT ARGUMENTS:
%   datasets  cell array of char  (dimensionless)
%       1-by-7 cell array of the dataset tags actually used, in the order:
%       {'ptCenter','ptPlusX','ptMinusX','ptPlusY','ptMinusY','ptPlusZ','ptMinusZ'}.
%
% COMSOL API CONSTRAINTS:
%   - model.result.dataset.create('<tag>', 'CutPoint3D') raises an error if
%     the tag already exists; always check model.result.dataset.tags first
%     (Requirement 7.4).
%   - CutPoint3D coordinates are set via dataset.set('pointx', x),
%     dataset.set('pointy', y), dataset.set('pointz', z) where x/y/z are
%     numeric scalars in metres (Requirement 7.1, 7.2).
%   - The solution is assigned via dataset.set('solution', comp_sol_id)
%     (Requirement 7.5).
%   - model.result.dataset.tags returns a Java StringArray; wrap with cell()
%     before use in MATLAB.
%
% REQUIREMENTS ADDRESSED: 7.1, 7.2, 7.4, 7.5
% --------------------------------------------------------------------------

    locations = get_point_locations();
    source_dataset_tag = resolve_solution_dataset_tag(model, comp_sol_id);

    % Get existing dataset tags once (avoid repeated API calls)
    try
        existing_tags = cell(model.result.dataset.tags);
    catch
        existing_tags = {};
    end

    datasets = cell(1, numel(locations));

    for i = 1:numel(locations)
        loc = locations(i);
        tag = loc.tag;

        % Create dataset only if tag is absent (Req 7.4)
        if ~any(strcmp(existing_tags, tag))
            try
                ds = model.result.dataset.create(tag, 'CutPoint3D');
            catch err
                % May have been created between our check and create; retrieve it
                try
                    ds = model.result.dataset(tag);
                catch
                    warning('Time_domain_extraction_GUI:datasetCreateFailed', ...
                        'Could not create or access dataset %s: %s', tag, err.message);
                    datasets{i} = tag;
                    continue;
                end
            end
        else
            ds = model.result.dataset(tag);
        end

        % Set coordinates (Req 7.1, 7.2)
        try
            ds.label(loc.name);
            ds.set('pointx', loc.x);
            ds.set('pointy', loc.y);
            ds.set('pointz', loc.z);
            if ~isempty(source_dataset_tag)
                ds.set('data', source_dataset_tag);
            end
            % Assign comparison solution (Req 7.5)
            ds.set('solution', comp_sol_id);
            try
                ds.set('sol', comp_sol_id);
            catch
            end
        catch err
            warning('Time_domain_extraction_GUI:datasetSetFailed', ...
                'Could not configure dataset %s: %s', tag, err.message);
        end

        datasets{i} = tag;
    end

end

% --------------------------------------------------------------------------
function [t_vec, beddy_uT] = extract_point_data(model, pt_tag, ref_sol_id, comp_sol_id, export_path)
% extract_point_data  Extract a point time-trace through PlotGroup1D + export.

    t_vec    = [];
    beddy_uT = [];

    reference_sol_id = strtrim(ref_sol_id);
    if isempty(reference_sol_id)
        reference_sol_id = strtrim(comp_sol_id);
    end

    % Current dataset/plot is tied to the selected comparison solution.
    % Subtract the Reference-study solution to obtain non-zero Beddy traces.
    expr = sprintf('mf.By-withsol(''%s'',mf.By,setval(t,t))', reference_sol_id);

    ensure_point_plot_export(model, pt_tag, expr, export_path);
    [t_vec, beddy_uT] = read_comsol_point_export(export_path);

    if isempty(t_vec) || isempty(beddy_uT)
        error('extract_point_data:EvaluationFailed', ...
            'COMSOL export returned no valid numeric point-trace data for dataset %s.', pt_tag);
    end
end

% --------------------------------------------------------------------------
function file_path = write_output_file(out_folder, location, axis, val_mm, t_vec, beddy_uT)
% write_output_file  Write a tab-separated time/Beddy data file to disk.
%
% PURPOSE:
%   Builds the output filename from the location, optional offset axis and
%   value, creates the appropriate sub-folder inside out_folder if it does
%   not exist, and writes a two-column tab-separated text file with a one-
%   line header.
%
% INPUT ARGUMENTS:
%   out_folder  char  (dimensionless — filesystem path)
%       Root output directory chosen by the user.
%   location    char  (dimensionless)
%       Measurement location name; one of:
%       'Center', '+X', '-X', '+Y', '-Y', '+Z', '-Z'.
%   axis        char or []  (dimensionless)
%       Offset axis label ('X', 'Y', or 'Z') for offset files.
%       Pass [] or '' for nominal (no-offset) files.
%   val_mm      double scalar or []  (millimetres)
%       Offset magnitude in millimetres for offset files.
%       Pass [] or 0 for nominal files.
%   t_vec       double column vector  (seconds)
%       Time values to write in the first column.
%   beddy_uT    double column vector  (micro-Tesla, µT)
%       Beddy values to write in the second column.
%
% OUTPUT ARGUMENTS:
%   file_path   char  (dimensionless — filesystem path)
%       Full path of the file that was written (or would have been written).
%
% COMSOL API CONSTRAINTS:
%   None — this function performs only MATLAB file I/O.
%
% FILE FORMAT:
%   Header row:  t_s<TAB>Beddy_uT
%   Data rows:   <time_seconds><TAB><beddy_microTesla>
%   Encoding:    UTF-8, line endings per host OS.
%
    % NAMING CONVENTION:
    %   Nominal:  Beddy_Time_Point_<Location>.txt
    %   Offset:   Beddy_Time_Point_<Location>_Offset_<Axis>_<Value>mm.txt
%             where <Value> is an integer string when val_mm is whole,
%             else a decimal string (see format_offset_value).
% --------------------------------------------------------------------------

    if numel(t_vec) ~= numel(beddy_uT)
        error('write_output_file:LengthMismatch', ...
            't_vec and beddy_uT must have the same number of elements.');
    end

    loc_folder = fullfile(out_folder, location);
    if ~exist(loc_folder, 'dir')
        mkdir(loc_folder);
    end

    if nargin < 3 || isempty(axis)
        fname = sprintf('Beddy_Time_Point_%s.txt', location);
    else
        axis_chr = upper(axis(1));
        val_str = format_offset_value(val_mm);
        fname = sprintf('Beddy_Time_Point_%s_Offset_%s_%smm.txt', ...
            location, axis_chr, val_str);
    end

    file_path = fullfile(loc_folder, fname);

    fid = fopen(file_path, 'w');
    if fid < 0
        error('write_output_file:OpenFailed', 'Could not open file for writing: %s', file_path);
    end

    cleanup_obj = onCleanup(@() fclose(fid)); %#ok<NASGU>

    fprintf(fid, '%s\tBeddy_uT\n', infer_time_header_label(t_vec));
    for k = 1:numel(t_vec)
        fprintf(fid, '%.16g\t%.16g\n', t_vec(k), beddy_uT(k));
    end

end

% --------------------------------------------------------------------------
function label = infer_time_header_label(t_vec)
% infer_time_header_label  Choose a more accurate column header for exported time values.
    finite_t = t_vec(isfinite(t_vec));
    if isempty(finite_t)
        label = 't_s';
        return;
    end

    if max(abs(finite_t)) > 2
        label = 't_ms';
    else
        label = 't_s';
    end
end

% --------------------------------------------------------------------------
function [t_out, data_out] = apply_time_filter(t_vec, data_vec, filter_ms)
% apply_time_filter  Discard time samples earlier than a specified threshold.
%
% PURPOSE:
%   Retains only those rows of [t_vec, data_vec] where t_vec >= T_s, where
%   T_s = filter_ms / 1000.  If filter_ms is empty, zero, or only whitespace
%   (when passed as a string), all rows are returned unchanged.
%
% INPUT ARGUMENTS:
%   t_vec      double column vector  (seconds)
%       Time axis values from the COMSOL extraction.
%   data_vec   double column vector  (micro-Tesla, µT)
%       Beddy values aligned with t_vec.
%   filter_ms  double scalar or char  (milliseconds)
%       Threshold in milliseconds.  Pass '' or [] to skip filtering.
%       A numeric value <= 0 or a non-numeric string raises an error.
%
% OUTPUT ARGUMENTS:
%   t_out    double column vector  (seconds)
%       Filtered time values; all elements satisfy t_out >= T_s.
%   data_out double column vector  (micro-Tesla, µT)
%       Filtered Beddy values aligned with t_out.
%
% COMSOL API CONSTRAINTS:
%   None — this is a pure MATLAB data processing function.
%
% UNIT CONVERSION (Requirement 13.2):
%   T_s = filter_ms / 1000   [ms → s]
% --------------------------------------------------------------------------

    t_out    = t_vec;
    data_out = data_vec;

    if isempty(filter_ms)
        return;
    end

    % Allow either numeric input or strings like "100.4", ">=100.4", ">100.4", "=100.4".
    op = '>=';
    if isnumeric(filter_ms)
        threshold_ms = double(filter_ms);
    else
        txt = strtrim(char(filter_ms));
        if isempty(txt)
            return;
        end

        tokens = regexp(txt, '^([><]=?|=)?\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)$', ...
            'tokens', 'once');
        if isempty(tokens)
            error('apply_time_filter:InvalidInput', ...
                'Filter Time must be a positive number in ms (e.g., 100.4 or >=100.4).');
        end

        if ~isempty(tokens{1})
            op = tokens{1};
        end

        threshold_ms = str2double(tokens{2});
    end

    if isnan(threshold_ms) || ~isfinite(threshold_ms) || threshold_ms <= 0
        error('apply_time_filter:InvalidThreshold', ...
            'Filter Time must be a positive number in ms.');
    end

    threshold_native = convert_filter_threshold_to_time_axis_units(t_vec, threshold_ms);
    switch op
        case '>'
            mask = (t_vec > threshold_native);
        otherwise
            mask = (t_vec >= threshold_native);
    end

    t_out = t_vec(mask);
    data_out = data_vec(mask);

end

% --------------------------------------------------------------------------
function str = format_offset_value(val_mm)
% format_offset_value  Format an offset magnitude (mm) as a filename string.
%
% PURPOSE:
%   Returns an integer string (e.g., '10') when val_mm is a whole number,
%   and a decimal string (e.g., '5.5') otherwise.  Used to build output
%   filenames that encode the offset value without redundant decimal points.
%
% INPUT ARGUMENTS:
%   val_mm  double scalar  (millimetres)
%       Offset magnitude to format.  Must be finite and non-negative.
%
% OUTPUT ARGUMENTS:
%   str  char  (dimensionless)
%       String representation of val_mm suitable for use in a filename.
%       Examples:
%           format_offset_value(10)   → '10'
%           format_offset_value(5.5)  → '5.5'
%           format_offset_value(0)    → '0'
%
% COMSOL API CONSTRAINTS:
%   None — pure MATLAB string formatting.
%
% REQUIREMENT: 10.2
% --------------------------------------------------------------------------

    if mod(val_mm, 1) == 0
        str = sprintf('%d', int32(val_mm));
    else
        str = sprintf('%g', val_mm);
    end

end

% --------------------------------------------------------------------------
function sol_id = resolve_sol_id(model, study_tag)
% resolve_sol_id  Dynamically resolve the solver solution ID for a study.
%
% PURPOSE:
%   Cross-references model.sol.tags against each study's solver feature tree
%   to find the solution tag (e.g., 'sol1', 'sol6') that was produced by the
%   given study.  No solution ID is ever hardcoded; the mapping is derived
%   entirely from the live model object.
%
% INPUT ARGUMENTS:
%   model      com.comsol.model.impl.ModelImpl  (dimensionless — Java object)
%       Live COMSOL model handle.
%   study_tag  char  (dimensionless)
%       COMSOL study tag to resolve (e.g., 'std1').
%
% OUTPUT ARGUMENTS:
%   sol_id  char  (dimensionless)
%       Solution tag associated with the study (e.g., 'sol1').
%       Returns '' if no matching solution can be found.
%
% COMSOL API CONSTRAINTS:
%   - Primary strategy: iterate model.sol.tags; for each sol tag check
%     whether model.sol('<sol_tag>').study returns study_tag.
%   - Fallback strategy: iterate model.study('<study_tag>').feature.tags
%     looking for a solver feature of type 'Stationary', 'Transient', or
%     'Eigenvalue' that references a sol tag via its 'sol' property.
%   - Both model.sol and model.study APIs return Java StringArrays; always
%     wrap with cell() before iterating.
%   - Never hardcode any solution ID string (Requirement 2.2, 8.2).
% --------------------------------------------------------------------------

    sol_id = '';

    % ------------------------------------------------------------------
    %  Primary strategy: iterate model.sol.tags and check which sol node
    %  was produced by study_tag.
    % ------------------------------------------------------------------
    try
        sol_tags = cell(model.sol.tags);
        for i = 1:numel(sol_tags)
            st = sol_tags{i};
            try
                linked_study = char(model.sol(st).study);
                if strcmp(linked_study, study_tag)
                    sol_id = st;
                    return;
                end
            catch
                % This sol node may not have a study attribute; skip it.
            end
        end
    catch
        % model.sol may not exist in this model version; fall through.
    end

    % ------------------------------------------------------------------
    %  Fallback strategy: inspect study feature tree for a solver step
    %  that references a sol tag via its 'sol' property.
    % ------------------------------------------------------------------
    try
        feat_tags = cell(model.study(study_tag).feature.tags);
        solver_types = {'Stationary', 'Transient', 'Eigenvalue', ...
                        'StationarySolver', 'TransientSolver'};
        for i = 1:numel(feat_tags)
            ft = feat_tags{i};
            try
                ftype = char(model.study(study_tag).feature(ft).getType());
                if any(strcmp(ftype, solver_types))
                    try
                        candidate = char(model.study(study_tag).feature(ft).getString('sol'));
                        if ~isempty(candidate)
                            sol_id = candidate;
                            return;
                        end
                    catch
                        % 'sol' property absent for this feature; continue.
                    end
                end
            catch
                % Feature type query failed; skip.
            end
        end
    catch
        % Study feature tree unavailable; give up.
    end

end

% --------------------------------------------------------------------------
function after_model_load(fig)
% after_model_load  Update GUI state after a model has been loaded successfully.
%
% PURPOSE:
%   Called by the "Browse Model" callback once load_model returns a valid
%   model handle.  Runs study detection, validates the Reference study,
%   populates the Comparison Study drop-down, re-enables extraction controls,
%   and updates the reference solution label.
%
% INPUT ARGUMENTS:
%   fig  matlab.ui.Figure  (dimensionless)
%       Handle to the main uifigure whose UserData contains the app struct.
%
% OUTPUT ARGUMENTS:
%   (none — all updates are applied directly to fig.UserData)
%
% COMSOL API CONSTRAINTS:
%   - detect_studies must be called before any extraction controls are enabled.
%   - If no 'Reference' study is found, extraction controls remain disabled.
%
% REQUIREMENTS ADDRESSED: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.3, 4.4
% --------------------------------------------------------------------------

    app = fig.UserData;

    % Start from a conservative disabled state; we only re-enable controls
    % after both the reference and comparison study selections are valid.
    app.studyDropdown.Enable    = 'off';
    app.filterTimeField.Enable  = 'off';
    app.applyOffsetCheck.Enable = 'off';
    app.extractBtn.Enable       = 'off';
    app.comp_sol_id             = '';

    % Step 2 — Detect studies and cache in app state
    studies = detect_studies(app.model);
    app.studies = studies;

    % Step 3 — Find Reference study
    ref_idx = [];
    for k = 1:numel(studies)
        if strcmp(studies(k).label, 'Reference')
            ref_idx = k;
            break;
        end
    end

    % Step 4 — No Reference study found: alert, update label, return
    if isempty(ref_idx)
        uialert(fig, ...
            ['No study labelled ''Reference'' was found in the model. ' ...
             'Extraction cannot proceed.'], ...
            'Missing Reference Study', ...
            'Icon', 'error');
        app.refSolLabel.Text = 'Reference solution: NOT FOUND';
        fig.UserData = app;
        return;
    end

    % Step 5 — Store ref_sol_id and update label (Req 2.4)
    app.ref_sol_id = studies(ref_idx).sol_id;
    app.refSolLabel.Text = ['Reference solution: ' app.ref_sol_id];
    if isempty(app.ref_sol_id)
        uialert(fig, ...
            ['The study labelled ''Reference'' was found, but its solution ID ' ...
             'could not be resolved. Extraction cannot proceed.'], ...
            'Reference Solution Not Resolved', ...
            'Icon', 'error');
        fig.UserData = app;
        return;
    end

    % Step 6 — Build comparison labels, excluding Reference and unresolved studies.
    comp_labels = {};
    for k = 1:numel(studies)
        if k ~= ref_idx && ~isempty(studies(k).sol_id)
            comp_labels{end+1} = studies(k).label; %#ok<AGROW>
        end
    end

    % Step 7 — Guard against zero valid non-Reference studies.
    if isempty(comp_labels)
        app.studyDropdown.Items = {'(none available)'};
        app.studyDropdown.Value = '(none available)';
        gui_log(app.logArea, ...
            'Model loaded, but no non-Reference study with a resolved solution ID is available.');
        fig.UserData = app;
        uialert(fig, ...
            ['No comparison study with a resolved solution ID was found. ' ...
             'Extraction remains disabled.'], ...
            'Missing Comparison Study', ...
            'Icon', 'warning');
        return;
    end

    % Step 8 — Populate drop-down (Req 2.5, 2.6)
    app.studyDropdown.Items = comp_labels;
    app.studyDropdown.Value = comp_labels{1};

    % Step 9 — Resolve comp_sol_id for the pre-selected study
    sel_label = comp_labels{1};
    app.comp_sol_id = '';
    for k = 1:numel(studies)
        if strcmp(studies(k).label, sel_label)
            app.comp_sol_id = studies(k).sol_id;
            break;
        end
    end

    % Step 10 — Guard against a pre-selected study without a valid solution.
    if isempty(app.comp_sol_id)
        gui_log(app.logArea, ...
            ['Model loaded, but the selected comparison study "' sel_label ...
             '" has no resolved solution ID.']);
        fig.UserData = app;
        uialert(fig, ...
            ['The selected comparison study "' sel_label ...
             '" does not have a resolved solution ID. Extraction remains disabled.'], ...
            'Comparison Solution Not Resolved', ...
            'Icon', 'warning');
        return;
    end

    % Step 11 — Wire ValueChangedFcn so selection changes update comp_sol_id
    app.studyDropdown.ValueChangedFcn = @(src, ~) cb_study_changed(fig, src.Value);

    % Step 12 — Re-enable extraction controls (Req 4.4)
    app.studyDropdown.Enable    = 'on';
    app.filterTimeField.Enable  = 'on';
    app.applyOffsetCheck.Enable = 'on';

    % Step 13 — Enable Extract button when Point or Cylinder analysis is selected
    if app.rbPoint.Value || app.rbCylinder.Value
        app.extractBtn.Enable = 'on';
    end

    if app.rbCylinder.Value
        app.radiusField.Enable = 'on';
        app.heightField.Enable = 'on';
        app.radiusLabel.Visible = 'on';
        app.radiusField.Visible = 'on';
        app.heightLabel.Visible = 'on';
        app.heightField.Visible = 'on';
    end

    % Step 14 — Log summary message
    gui_log(app.logArea, ['Model loaded. ' num2str(numel(studies)) ' studies found.']);

    % Step 15 — Persist state
    fig.UserData = app;
end

% --------------------------------------------------------------------------
function threshold_native = convert_filter_threshold_to_time_axis_units(t_vec, threshold_ms)
% convert_filter_threshold_to_time_axis_units  Match filter units to exported COMSOL time axis.
%
% COMSOL plot exports in this workflow often come out in milliseconds even
% when older helper code assumed seconds. If the exported time values are
% clearly larger than a few seconds, treat them as milliseconds.
    finite_t = t_vec(isfinite(t_vec));
    if isempty(finite_t)
        threshold_native = threshold_ms / 1000;
        return;
    end

    max_abs_t = max(abs(finite_t));
    if max_abs_t > 2
        threshold_native = threshold_ms;
    else
        threshold_native = threshold_ms / 1000;
    end
end

% --------------------------------------------------------------------------
function locations = get_point_locations()
% get_point_locations  Canonical point definitions required by the workflow.
    locations = struct( ...
        'name', {'Center','+X','-X','+Y','-Y','+Z','-Z'}, ...
        'tag',  {'ptCenter','ptPlusX','ptMinusX','ptPlusY','ptMinusY','ptPlusZ','ptMinusZ'}, ...
        'x',    {0,  0.05, -0.05, 0,     0,     0,     0    }, ...
        'y',    {0,  0,     0,    0.05, -0.05,  0,     0    }, ...
        'z',    {0,  0,     0,    0,     0,     0.05, -0.05});
end

% --------------------------------------------------------------------------
function configure_point_dataset_position(model, ds_tag, loc_name, axis_name, offset_mm)
% configure_point_dataset_position  Update one CutPoint3D dataset position in metres.
    locations = get_point_locations();
    match_idx = [];
    for i = 1:numel(locations)
        if strcmp(locations(i).name, loc_name) || strcmp(locations(i).tag, ds_tag)
            match_idx = i;
            break;
        end
    end

    if isempty(match_idx)
        error('configure_point_dataset_position:UnknownLocation', ...
            'Unknown point location "%s" / dataset "%s".', loc_name, ds_tag);
    end

    x_m = locations(match_idx).x;
    y_m = locations(match_idx).y;
    z_m = locations(match_idx).z;

    if ~isempty(axis_name) && ~isempty(offset_mm)
        offset_m = offset_mm * 1e-3;
        switch upper(axis_name)
            case 'X'
                x_m = x_m + offset_m;
            case 'Y'
                y_m = y_m + offset_m;
            case 'Z'
                z_m = z_m + offset_m;
            otherwise
                error('configure_point_dataset_position:InvalidAxis', ...
                    'Unsupported axis "%s".', axis_name);
        end
    end

    model.result.dataset(ds_tag).set('pointx', x_m);
    model.result.dataset(ds_tag).set('pointy', y_m);
    model.result.dataset(ds_tag).set('pointz', z_m);
end

% --------------------------------------------------------------------------
function dataset_tag = resolve_solution_dataset_tag(model, comp_sol_id)
% resolve_solution_dataset_tag  Find a result dataset associated with a solution tag.
    dataset_tag = '';

    try
        dataset_tags = cell(model.result.dataset.tags);
    catch
        dataset_tags = {};
    end

    for i = 1:numel(dataset_tags)
        tag = char(dataset_tags{i});
        ds = [];
        try
            ds = model.result.dataset(tag);
        catch
        end
        if isempty(ds)
            continue;
        end

        prop_names = {'solution', 'sol'};
        for p = 1:numel(prop_names)
            try
                value = char(ds.getString(prop_names{p}));
                if strcmp(strtrim(value), comp_sol_id)
                    dataset_tag = tag;
                    return;
                end
            catch
            end
        end
    end

    for i = 1:numel(dataset_tags)
        tag = char(dataset_tags{i});
        if startsWith(tag, 'dset')
            dataset_tag = tag;
            return;
        end
    end
end

% --- Req 3.2 ---------------------------------------------------------------
function cb_study_changed(fig, selected_label)
% cb_study_changed  Update comp_sol_id when the user selects a different study.
%
% PURPOSE:
%   Fired by studyDropdown.ValueChangedFcn whenever the user picks a new
%   entry in the Comparison Study drop-down.  Looks up the corresponding
%   Solution_ID from the cached studies struct array and stores it in
%   fig.UserData so the Extract callback always operates on the current
%   selection.
%
% INPUT ARGUMENTS:
%   fig             matlab.ui.Figure  (dimensionless)
%       Handle to the main uifigure whose UserData contains the app struct.
%   selected_label  char  (dimensionless)
%       Human-readable study label chosen by the user (e.g., 'AllPlates').
%
% OUTPUT ARGUMENTS:
%   (none — fig.UserData.comp_sol_id is updated in place)
%
% COMSOL API CONSTRAINTS:
%   None — reads only from the cached studies struct; no live model calls.
%
% REQUIREMENTS ADDRESSED: 3.2
% --------------------------------------------------------------------------

    app = fig.UserData;
    studies = app.studies;
    app.comp_sol_id = '';

    for k = 1:numel(studies)
        if strcmp(studies(k).label, selected_label)
            app.comp_sol_id = studies(k).sol_id;
            break;
        end
    end

    if isempty(app.comp_sol_id)
        app.extractBtn.Enable = 'off';
    elseif (app.rbPoint.Value || app.rbCylinder.Value) && ~isempty(app.model)
        app.extractBtn.Enable = 'on';
    end

    fig.UserData = app;
end

% --------------------------------------------------------------------------
function [offsets_mm, valid] = parse_offset_field(field_str, fig)
% parse_offset_field  Parse an offset text-field string into a numeric vector.
%
% PURPOSE:
%   Converts the raw text entered by the user in an offset field (X, Y, or Z)
%   into a validated numeric row vector expressed in millimetres.  Handles:
%     - Empty / whitespace-only input  → treated as a single 0 mm value
%     - Single numeric value           → [val_mm]
%     - Comma-separated list           → [val1_mm, val2_mm, …]
%   Validation errors are surfaced via ui_errordlg (blocking) or uiconfirm
%   (non-blocking warning that lets the user cancel).
%
% INPUT ARGUMENTS:
%   field_str  char  (dimensionless)
%       Raw text from the offset edit-field, e.g. '10', '10,20,30', '-5'.
%   fig        matlab.ui.Figure  (dimensionless)
%       Handle to the main uifigure; used as the parent for uiconfirm.
%
% OUTPUT ARGUMENTS:
%   offsets_mm  double row vector  (millimetres)
%       Parsed offset values in mm.  Empty ([]) when valid is false.
%   valid       logical scalar
%       true  — parsed successfully; caller may proceed.
%       false — a blocking error was raised or the user cancelled; caller
%               must abort extraction.
%
% REQUIREMENTS ADDRESSED: 5.4, 5.5, 5.6, 13.1, 13.4
% --------------------------------------------------------------------------

    % Default outputs
    offsets_mm = [];
    valid      = false;

    % ------------------------------------------------------------------
    % 1. Empty / whitespace → nominal-only (Req 5.7)
    % ------------------------------------------------------------------
    if isempty(strtrim(field_str))
        offsets_mm = 0;
        valid      = true;
        return;
    end

    % ------------------------------------------------------------------
    % 2. Parse comma-separated tokens
    % ------------------------------------------------------------------
    tokens = strsplit(field_str, ',');
    vals   = zeros(1, numel(tokens));

    for k = 1:numel(tokens)
        v = str2double(strtrim(tokens{k}));
        if isnan(v)
            ui_errordlg(fig, ...
                'Invalid offset value: must be numeric (e.g. 10 or 10,20,30).', ...
                'Invalid Offset');
            return;   % offsets_mm = [], valid = false
        end
        vals(k) = v;
    end

    % ------------------------------------------------------------------
    % 3. Range check in metres (Req 13.4): warn if outside [-1, 1] m
    % ------------------------------------------------------------------
    vals_m = vals * 1e-3;   % mm → m  (Req 13.1)

    if any(abs(vals_m) > 1)
        answer = uiconfirm(fig, ...
            ['One or more offset values are outside the expected range ' ...
             '(±1 m).  Proceeding may produce incorrect results.'], ...
            'Large Offset Warning', ...
            'Options',     {'Continue', 'Cancel'}, ...
            'DefaultOption', 'Cancel', ...
            'CancelOption',  'Cancel', ...
            'Icon',          'warning');
        if strcmp(answer, 'Cancel')
            return;   % offsets_mm = [], valid = false
        end
    end

    % ------------------------------------------------------------------
    % 4. Return values in mm; valid = true
    % ------------------------------------------------------------------
    offsets_mm = vals;
    valid      = true;
end

% --------------------------------------------------------------------------
function cb_cancel(fig)
% cb_cancel  Request cancellation of the active extraction session.
    app = fig.UserData;
    app.cancel_requested = true;
    fig.UserData = app;
    gui_log(app.logArea, 'Cancel requested. Extraction will stop after the current file.');
end

% --------------------------------------------------------------------------
function cb_extract(fig)
% cb_extract  Run the end-to-end point extraction workflow.

    app = fig.UserData;

    if isempty(app.model)
        ui_errordlg(fig, 'Please load a COMSOL model before extracting.', 'Missing Model');
        return;
    end

    if isempty(app.ref_sol_id) || isempty(app.comp_sol_id)
        ui_errordlg(fig, 'Could not resolve reference/comparison solution IDs.', 'Missing Solution ID');
        return;
    end

    if app.rbCylinder.Value
        run_cylinder_extraction(fig);
        return;
    end

    if ~app.rbPoint.Value
        ui_errordlg(fig, 'Please select Point or Cylinder analysis type.', 'Missing Analysis Type');
        return;
    end

    out_folder = strtrim(app.outputFolderField.Value);
    if isempty(out_folder)
        ui_errordlg(fig, 'Please select an output folder before extracting.', 'Missing Output Folder');
        return;
    end

    if ~exist(out_folder, 'dir')
        try
            mkdir(out_folder);
        catch err
            ui_errordlg(fig, err.message, 'Output Folder Error');
            return;
        end
    end

    % Validate time filter input once up-front.
    filter_text = app.filterTimeField.Value;
    try
        apply_time_filter([0; 1], [0; 1], filter_text);
    catch err
        ui_errordlg(fig, err.message, 'Invalid Time Filter');
        return;
    end

    % Parse offsets when enabled.
    x_vals_mm = [];
    y_vals_mm = [];
    z_vals_mm = [];

    if app.applyOffsetCheck.Value
        [x_vals_mm, okx] = parse_offset_field(app.offsetXField.Value, fig);
        if ~okx, return; end
        [y_vals_mm, oky] = parse_offset_field(app.offsetYField.Value, fig);
        if ~oky, return; end
        [z_vals_mm, okz] = parse_offset_field(app.offsetZField.Value, fig);
        if ~okz, return; end

        x_vals_mm = x_vals_mm(x_vals_mm ~= 0);
        y_vals_mm = y_vals_mm(y_vals_mm ~= 0);
        z_vals_mm = z_vals_mm(z_vals_mm ~= 0);
    end

    point_locations = get_point_locations();
    locations = {point_locations.name};

    % Ensure the required output folder structure exists.
    for i = 1:numel(locations)
        folder_i = fullfile(out_folder, locations{i});
        if ~exist(folder_i, 'dir')
            mkdir(folder_i);
        end
    end

    % Create/reuse canonical point datasets.
    dataset_tags = create_point_datasets(app.model, app.comp_sol_id);

    total_jobs = numel(locations);
    if app.applyOffsetCheck.Value
        total_jobs = total_jobs + numel(locations) * ...
            (numel(x_vals_mm) + numel(y_vals_mm) + numel(z_vals_mm));
    end

    app.cancel_requested = false;
    app.overwrite_policy = 'unset';
    app.extractBtn.Enable = 'off';
    app.cancelBtn.Enable = 'on';
    app.progressLabel.Text = sprintf('Starting extraction (0/%d)...', total_jobs);
    fig.UserData = app;

    written_count = 0;
    skipped_count = 0;
    error_count = 0;
    job_index = 0;
    cancelled = false;

    for i = 1:numel(locations)
        loc_name = locations{i};
        ds_tag = dataset_tags{i};

        % Always nominal first.
        [job_index, written_count, skipped_count, error_count] = ...
            process_one_point(fig, app.model, out_folder, loc_name, ds_tag, ...
                app.ref_sol_id, app.comp_sol_id, filter_text, ...
                [], [], job_index, total_jobs, written_count, skipped_count, error_count);

        drawnow;
        app = fig.UserData;
        if app.cancel_requested
            cancelled = true;
            break;
        end

        if app.applyOffsetCheck.Value
            for vx = x_vals_mm
                [job_index, written_count, skipped_count, error_count] = ...
                    process_one_point(fig, app.model, out_folder, loc_name, ds_tag, ...
                        app.ref_sol_id, app.comp_sol_id, filter_text, ...
                        'X', vx, job_index, total_jobs, written_count, skipped_count, error_count);

                drawnow;
                app = fig.UserData;
                if app.cancel_requested
                    cancelled = true;
                    break;
                end
            end
            if cancelled, break; end

            for vy = y_vals_mm
                [job_index, written_count, skipped_count, error_count] = ...
                    process_one_point(fig, app.model, out_folder, loc_name, ds_tag, ...
                        app.ref_sol_id, app.comp_sol_id, filter_text, ...
                        'Y', vy, job_index, total_jobs, written_count, skipped_count, error_count);

                drawnow;
                app = fig.UserData;
                if app.cancel_requested
                    cancelled = true;
                    break;
                end
            end
            if cancelled, break; end

            for vz = z_vals_mm
                [job_index, written_count, skipped_count, error_count] = ...
                    process_one_point(fig, app.model, out_folder, loc_name, ds_tag, ...
                        app.ref_sol_id, app.comp_sol_id, filter_text, ...
                        'Z', vz, job_index, total_jobs, written_count, skipped_count, error_count);

                drawnow;
                app = fig.UserData;
                if app.cancel_requested
                    cancelled = true;
                    break;
                end
            end
            if cancelled, break; end
        end
    end

    % Reset offsets to nominal baseline at the end of a run.
    set_offset_params(app.model, 0, 0, 0);

    app = fig.UserData;
    app.cancel_requested = false;
    app.cancelBtn.Enable = 'off';
    if app.rbPoint.Value && ~isempty(app.model)
        app.extractBtn.Enable = 'on';
    end

    if cancelled
        app.progressLabel.Text = sprintf('Cancelled (%d/%d).', job_index, total_jobs);
        fig.UserData = app;
        uialert(fig, ...
            sprintf('Extraction cancelled. Written: %d, Skipped: %d, Errors: %d.', ...
                written_count, skipped_count, error_count), ...
            'Extraction Cancelled', ...
            'Icon', 'warning');
        return;
    end

    app.progressLabel.Text = sprintf('Completed (%d/%d).', job_index, total_jobs);
    fig.UserData = app;

    uialert(fig, ...
        sprintf('Extraction complete. Written: %d, Skipped: %d, Errors: %d.', ...
            written_count, skipped_count, error_count), ...
        'Extraction Complete', ...
        'Icon', 'success');
end

% --------------------------------------------------------------------------
function [job_index, written_count, skipped_count, error_count] = process_one_point( ...
    fig, model, out_folder, loc_name, ds_tag, ref_sol_id, comp_sol_id, filter_text, ...
    axis_name, offset_mm, job_index, total_jobs, written_count, skipped_count, error_count)
% process_one_point  Evaluate and export a single nominal/offset point trace.

    app = fig.UserData;

    job_index = job_index + 1;
    app.progressLabel.Text = sprintf('Processing %d/%d: %s', job_index, total_jobs, loc_name);
    fig.UserData = app;

    try
        target_path = compose_output_file_path(out_folder, loc_name, axis_name, offset_mm);
        [allow_write, app.overwrite_policy] = evaluate_overwrite(target_path, app.overwrite_policy, fig);
        fig.UserData = app;
        if ~allow_write
            skipped_count = skipped_count + 1;
            gui_log(app.logArea, ['SKIP (exists): ' target_path]);
            return;
        end

        if isempty(axis_name)
            set_offset_params(model, 0, 0, 0);
            update_solution_after_offset(model, comp_sol_id);
            eval_ds_tag = ds_tag;
        else
            set_offset_params_for_axis(model, axis_name, offset_mm * 1e-3);
            update_solution_after_offset(model, comp_sol_id);
            eval_ds_tag = create_offset_point_dataset(model, loc_name, axis_name, offset_mm, comp_sol_id);
        end

        [t_vec, b_uT] = extract_point_data(model, eval_ds_tag, ref_sol_id, comp_sol_id, target_path);

        [t_f, b_f] = apply_time_filter(t_vec, b_uT, filter_text);
        if isempty(t_f)
            gui_log(app.logArea, ...
                sprintf('WARN: Filter removed all samples for %s (%s).', ...
                    loc_name, format_case_label(axis_name, offset_mm)));
            skipped_count = skipped_count + 1;
            return;
        end

        write_output_file(out_folder, loc_name, axis_name, offset_mm, t_f, b_f);
        written_count = written_count + 1;
        gui_log(app.logArea, ['OK: ' target_path]);
    catch err
        error_count = error_count + 1;
        gui_log(app.logArea, ...
            sprintf('ERROR [%s, %s]: %s', loc_name, format_case_label(axis_name, offset_mm), err.message));
    end
end

% --------------------------------------------------------------------------
function label = format_case_label(axis_name, offset_mm)
% format_case_label  Human-readable nominal/offset descriptor for logging.
    if isempty(axis_name)
        label = 'Nominal';
    else
        label = sprintf('Offset%s=%smm', upper(axis_name(1)), format_offset_value(offset_mm));
    end
end

% --------------------------------------------------------------------------
function file_path = compose_output_file_path(out_folder, location, axis, val_mm)
% compose_output_file_path  Build the exact output file path without writing.
    if isempty(axis)
        fname = sprintf('Beddy_Time_Point_%s.txt', location);
    else
        fname = sprintf('Beddy_Time_Point_%s_Offset_%s_%smm.txt', ...
            location, upper(axis(1)), format_offset_value(val_mm));
    end
    file_path = fullfile(out_folder, location, fname);
end

% --------------------------------------------------------------------------
function [allow_write, policy] = evaluate_overwrite(file_path, policy, fig)
% evaluate_overwrite  Apply session-level overwrite policy for one file.

    allow_write = true;
    if ~exist(file_path, 'file')
        return;
    end

    switch lower(policy)
        case 'yesall'
            allow_write = true;
            return;
        case 'noall'
            allow_write = false;
            return;
    end

    choice = uiconfirm(fig, ...
        sprintf('File already exists:\n%s\n\nOverwrite?', file_path), ...
        'Overwrite File', ...
        'Options', {'Yes', 'No', 'Yes to All', 'No to All'}, ...
        'DefaultOption', 'No', ...
        'CancelOption', 'No');

    switch choice
        case 'Yes to All'
            policy = 'yesall';
            allow_write = true;
        case 'No to All'
            policy = 'noall';
            allow_write = false;
        case 'Yes'
            allow_write = true;
        otherwise
            allow_write = false;
    end
end

% --------------------------------------------------------------------------
function set_offset_params(model, x_m, y_m, z_m)
% set_offset_params  Set both Offset_* and Point_offset_* COMSOL parameters in metres.
    set_single_param(model, 'Offset_x', x_m);
    set_single_param(model, 'Offset_y', y_m);
    set_single_param(model, 'Offset_z', z_m);
    set_single_param(model, 'Point_offset_x', x_m);
    set_single_param(model, 'Point_offset_y', y_m);
    set_single_param(model, 'Point_offset_z', z_m);
end

% --------------------------------------------------------------------------
function set_single_param(model, param_name, value_m)
% set_single_param  Robust parameter assignment supporting models with/without units.
    try
        model.param.set(param_name, sprintf('%g[m]', value_m));
    catch
        try
            model.param.set(param_name, sprintf('%g', value_m));
        catch
        end
    end
end

% --------------------------------------------------------------------------
function set_offset_params_for_axis(model, axis_name, offset_m)
% set_offset_params_for_axis  Apply one-axis offset while zeroing the others.
    x_m = 0; y_m = 0; z_m = 0;
    switch upper(axis_name)
        case 'X'
            x_m = offset_m;
        case 'Y'
            y_m = offset_m;
        case 'Z'
            z_m = offset_m;
        otherwise
            error('set_offset_params_for_axis:InvalidAxis', ...
                'Unsupported axis "%s".', axis_name);
    end
    set_offset_params(model, x_m, y_m, z_m);
end

% --------------------------------------------------------------------------
function update_solution_after_offset(model, sol_id)
% update_solution_after_offset  Refresh the selected COMSOL solution after offset changes.
    if isempty(strtrim(sol_id))
        return;
    end

    try
        model.sol(sol_id).updateSolution;
    catch err
        error('update_solution_after_offset:Failed', ...
            'Could not update solution %s after offset change: %s', sol_id, err.message);
    end
end

% --------------------------------------------------------------------------
function dataset_tag = create_offset_point_dataset(model, loc_name, axis_name, offset_mm, comp_sol_id)
% create_offset_point_dataset  Create a dedicated offset CutPoint3D dataset for one extraction.
    locations = get_point_locations();
    source_dataset_tag = resolve_solution_dataset_tag(model, comp_sol_id);
    match_idx = [];
    for i = 1:numel(locations)
        if strcmp(locations(i).name, loc_name)
            match_idx = i;
            break;
        end
    end
    if isempty(match_idx)
        error('create_offset_point_dataset:UnknownLocation', ...
            'Unknown location "%s".', loc_name);
    end

    loc = locations(match_idx);
    dataset_tag = sprintf('cpt_%s_%s_%s', ...
        sanitize_location_token(loc_name), upper(axis_name), sanitize_offset_tag_value(offset_mm));

    try
        model.result.dataset.remove(dataset_tag);
    catch
    end

    model.result.dataset.create(dataset_tag, 'CutPoint3D');
    model.result.dataset(dataset_tag).label(sprintf('%s Offset %s %s mm', ...
        loc_name, upper(axis_name), format_offset_value(offset_mm)));
    if ~isempty(source_dataset_tag)
        model.result.dataset(dataset_tag).set('data', source_dataset_tag);
    end
    model.result.dataset(dataset_tag).set('pointx', compose_offset_coordinate_expr(loc.x, 'Offset_x'));
    model.result.dataset(dataset_tag).set('pointy', compose_offset_coordinate_expr(loc.y, 'Offset_y'));
    model.result.dataset(dataset_tag).set('pointz', compose_offset_coordinate_expr(loc.z, 'Offset_z'));
    try
        model.result.dataset(dataset_tag).set('solution', comp_sol_id);
    catch
    end
end

% --------------------------------------------------------------------------
function expr = compose_offset_coordinate_expr(base_value_m, offset_param_name)
% compose_offset_coordinate_expr  Build a COMSOL expression like 0.05+Offset_x.
    if abs(base_value_m) < eps
        expr = offset_param_name;
    elseif base_value_m > 0
        expr = sprintf('%.15g+%s', base_value_m, offset_param_name);
    else
        expr = sprintf('%.15g+%s', base_value_m, offset_param_name);
    end
end

% --------------------------------------------------------------------------
function token = sanitize_location_token(loc_name)
% sanitize_location_token  Convert UI location names into COMSOL-safe tag fragments.
    switch loc_name
        case 'Center'
            token = 'Center';
        case '+X'
            token = 'PlusX';
        case '-X'
            token = 'MinusX';
        case '+Y'
            token = 'PlusY';
        case '-Y'
            token = 'MinusY';
        case '+Z'
            token = 'PlusZ';
        case '-Z'
            token = 'MinusZ';
        otherwise
            token = regexprep(loc_name, '[^a-zA-Z0-9]', '_');
    end
end

% --------------------------------------------------------------------------
function token = sanitize_offset_tag_value(offset_mm)
% sanitize_offset_tag_value  Convert an offset value into a COMSOL-safe tag fragment.
    token = format_offset_value(offset_mm);
    token = strrep(token, '-', 'm');
    token = strrep(token, '.', 'p');
    token = [token 'mm'];
end

% --------------------------------------------------------------------------
function ensure_point_plot_export(model, dataset_tag, expr, export_path)
% ensure_point_plot_export  Configure the required PlotGroup1D + PointGraph + export workflow.
    if exist(export_path, 'file')
        delete(export_path);
    end

    try
        result_tags = cell(model.result.tags);
    catch
        result_tags = {};
    end

    if ~any(strcmp(result_tags, 'pg26'))
        model.result.create('pg26', 'PlotGroup1D');
    end
    model.result('pg26').set('data', dataset_tag);
    try
        model.result('pg26').label('TimeDomainPointExtraction');
    catch
    end

    try
        feature_tags = cell(model.result('pg26').feature.tags);
    catch
        feature_tags = {};
    end

    if ~any(strcmp(feature_tags, 'ptgr1'))
        model.result('pg26').create('ptgr1', 'PointGraph');
    end

    model.result('pg26').feature('ptgr1').set('data', dataset_tag);
    model.result('pg26').feature('ptgr1').set('expr', expr);
    model.result('pg26').feature('ptgr1').set('unit', 'uT');
    try
        model.result('pg26').feature('ptgr1').label('Beddy');
        model.result('pg26').feature('ptgr1').set('descr', 'Beddy Time Trace');
    catch
    end

    % Required repeated refresh calls for COMSOL dataset/result switching.
    model.result('pg26').run;
    model.result('pg26').run;
    model.result('pg26').run;

    try
        export_tags = cell(model.result.export.tags);
    catch
        export_tags = {};
    end

    if ~any(strcmp(export_tags, 'plot5'))
        model.result.export.create('plot5', 'pg26', 'ptgr1', 'Plot');
    end

    model.result.export('plot5').set('filename', export_path);
    model.result.export('plot5').run;
end

% --------------------------------------------------------------------------
function [t_vec, y_vec] = read_comsol_point_export(file_path)
% read_comsol_point_export  Parse the COMSOL text export from a PointGraph plot.
    t_vec = [];
    y_vec = [];

    if ~exist(file_path, 'file')
        return;
    end

    txt = fileread(file_path);
    lines = regexp(txt, '\r\n|\n|\r', 'split');
    t_vals = [];
    y_vals = [];

    for i = 1:numel(lines)
        nums = sscanf(lines{i}, '%f');
        if numel(nums) >= 2
            t_vals(end+1, 1) = nums(1); %#ok<AGROW>
            y_vals(end+1, 1) = nums(2); %#ok<AGROW>
        end
    end

    if isempty(t_vals) || isempty(y_vals)
        return;
    end

    finite_mask = isfinite(t_vals) & isfinite(y_vals);
    t_vec = t_vals(finite_mask);
    y_vec = y_vals(finite_mask);
end

% --------------------------------------------------------------------------
function run_cylinder_extraction(fig)
% run_cylinder_extraction  End-to-end cylinder volume-average extraction workflow.

    app = fig.UserData;

    out_folder = strtrim(app.outputFolderField.Value);
    if isempty(out_folder)
        ui_errordlg(fig, 'Please select an output folder before extracting.', 'Missing Output Folder');
        return;
    end

    if ~exist(out_folder, 'dir')
        try
            mkdir(out_folder);
        catch err
            ui_errordlg(fig, err.message, 'Output Folder Error');
            return;
        end
    end

    filter_text = app.filterTimeField.Value;
    try
        apply_time_filter([0; 1], [0; 1], filter_text);
    catch err
        ui_errordlg(fig, err.message, 'Invalid Time Filter');
        return;
    end

    [r_vals_mm, okr] = parse_dimension_field(app.radiusField.Value, 'Radius (mm)', fig);
    if ~okr, return; end
    [h_vals_mm, okh] = parse_dimension_field(app.heightField.Value, 'Height (mm)', fig);
    if ~okh, return; end

    x_vals_mm = [];
    y_vals_mm = [];
    z_vals_mm = [];

    if app.applyOffsetCheck.Value
        [x_vals_mm, okx] = parse_offset_field(app.offsetXField.Value, fig);
        if ~okx, return; end
        [y_vals_mm, oky] = parse_offset_field(app.offsetYField.Value, fig);
        if ~oky, return; end
        [z_vals_mm, okz] = parse_offset_field(app.offsetZField.Value, fig);
        if ~okz, return; end

        x_vals_mm = x_vals_mm(x_vals_mm ~= 0);
        y_vals_mm = y_vals_mm(y_vals_mm ~= 0);
        z_vals_mm = z_vals_mm(z_vals_mm ~= 0);
    end

    point_locations = get_point_locations();
    locations = {point_locations.name};

    for i = 1:numel(locations)
        folder_i = fullfile(out_folder, locations{i});
        if ~exist(folder_i, 'dir')
            mkdir(folder_i);
        end
    end

    dataset_tag = resolve_cylinder_dataset_tag(app.model, app.comp_sol_id);
    if isempty(dataset_tag)
        ui_errordlg(fig, ...
            'Could not resolve a comp2 volume dataset for cylinder extraction.', ...
            'Missing Dataset');
        return;
    end

    total_jobs = numel(h_vals_mm) * numel(r_vals_mm) * numel(locations);
    if app.applyOffsetCheck.Value
        total_jobs = total_jobs + numel(h_vals_mm) * numel(r_vals_mm) * numel(locations) * ...
            (numel(x_vals_mm) + numel(y_vals_mm) + numel(z_vals_mm));
    end

    app.cancel_requested = false;
    app.overwrite_policy = 'unset';
    app.extractBtn.Enable = 'off';
    app.cancelBtn.Enable = 'on';
    app.progressLabel.Text = sprintf('Starting cylinder extraction (0/%d)...', total_jobs);
    fig.UserData = app;

    written_count = 0;
    skipped_count = 0;
    error_count = 0;
    job_index = 0;
    cancelled = false;

    for h_mm = h_vals_mm
        for r_mm = r_vals_mm
            set_cylinder_geometry_params(app.model, r_mm, h_mm);
            refresh_cylinder_geometry_and_solutions(app.model, app.ref_sol_id, app.comp_sol_id);

            for i = 1:numel(locations)
                loc_name = locations{i};

                [job_index, written_count, skipped_count, error_count] = ...
                    process_one_cylinder(fig, app.model, out_folder, loc_name, ...
                        app.ref_sol_id, app.comp_sol_id, dataset_tag, filter_text, ...
                        h_mm, r_mm, [], [], job_index, total_jobs, ...
                        written_count, skipped_count, error_count);

                drawnow;
                app = fig.UserData;
                if app.cancel_requested
                    cancelled = true;
                    break;
                end

                if app.applyOffsetCheck.Value
                    for vx = x_vals_mm
                        [job_index, written_count, skipped_count, error_count] = ...
                            process_one_cylinder(fig, app.model, out_folder, loc_name, ...
                                app.ref_sol_id, app.comp_sol_id, dataset_tag, filter_text, ...
                                h_mm, r_mm, 'X', vx, job_index, total_jobs, ...
                                written_count, skipped_count, error_count);

                        drawnow;
                        app = fig.UserData;
                        if app.cancel_requested
                            cancelled = true;
                            break;
                        end
                    end
                    if cancelled, break; end

                    for vy = y_vals_mm
                        [job_index, written_count, skipped_count, error_count] = ...
                            process_one_cylinder(fig, app.model, out_folder, loc_name, ...
                                app.ref_sol_id, app.comp_sol_id, dataset_tag, filter_text, ...
                                h_mm, r_mm, 'Y', vy, job_index, total_jobs, ...
                                written_count, skipped_count, error_count);

                        drawnow;
                        app = fig.UserData;
                        if app.cancel_requested
                            cancelled = true;
                            break;
                        end
                    end
                    if cancelled, break; end

                    for vz = z_vals_mm
                        [job_index, written_count, skipped_count, error_count] = ...
                            process_one_cylinder(fig, app.model, out_folder, loc_name, ...
                                app.ref_sol_id, app.comp_sol_id, dataset_tag, filter_text, ...
                                h_mm, r_mm, 'Z', vz, job_index, total_jobs, ...
                                written_count, skipped_count, error_count);

                        drawnow;
                        app = fig.UserData;
                        if app.cancel_requested
                            cancelled = true;
                            break;
                        end
                    end
                    if cancelled, break; end
                end
            end
            if cancelled, break; end
        end
        if cancelled, break; end
    end

    set_cylinder_position_params(app.model, 0, 0, 0);

    app = fig.UserData;
    app.cancel_requested = false;
    app.cancelBtn.Enable = 'off';
    if app.rbCylinder.Value && ~isempty(app.model)
        app.extractBtn.Enable = 'on';
    end

    if cancelled
        app.progressLabel.Text = sprintf('Cancelled (%d/%d).', job_index, total_jobs);
        fig.UserData = app;
        uialert(fig, ...
            sprintf('Extraction cancelled. Written: %d, Skipped: %d, Errors: %d.', ...
                written_count, skipped_count, error_count), ...
            'Extraction Cancelled', ...
            'Icon', 'warning');
        return;
    end

    app.progressLabel.Text = sprintf('Completed (%d/%d).', job_index, total_jobs);
    fig.UserData = app;

    uialert(fig, ...
        sprintf('Extraction complete. Written: %d, Skipped: %d, Errors: %d.', ...
            written_count, skipped_count, error_count), ...
        'Extraction Complete', ...
        'Icon', 'success');
end

% --------------------------------------------------------------------------
function [vals_mm, valid] = parse_dimension_field(field_str, field_label, fig)
% parse_dimension_field  Parse a required radius/height field (mm).
    if isempty(strtrim(field_str))
        ui_errordlg(fig, sprintf('Please enter %s before extracting.', field_label), 'Missing Input');
        vals_mm = [];
        valid = false;
        return;
    end
    [vals_mm, valid] = parse_offset_field(field_str, fig);
end

% --------------------------------------------------------------------------
function [job_index, written_count, skipped_count, error_count] = process_one_cylinder( ...
    fig, model, out_folder, loc_name, ref_sol_id, comp_sol_id, dataset_tag, filter_text, ...
    h_mm, r_mm, axis_name, offset_mm, job_index, total_jobs, ...
    written_count, skipped_count, error_count)
% process_one_cylinder  Evaluate and export one cylinder volume-average trace.

    app = fig.UserData;

    job_index = job_index + 1;
    app.progressLabel.Text = sprintf('Processing %d/%d: %s h=%s r=%s', ...
        job_index, total_jobs, loc_name, format_offset_value(h_mm), format_offset_value(r_mm));
    fig.UserData = app;

    try
        target_path = compose_cylinder_output_file_path( ...
            out_folder, h_mm, r_mm, loc_name, axis_name, offset_mm);
        [allow_write, app.overwrite_policy] = evaluate_overwrite(target_path, app.overwrite_policy, fig);
        fig.UserData = app;
        if ~allow_write
            skipped_count = skipped_count + 1;
            gui_log(app.logArea, ['SKIP (exists): ' target_path]);
            return;
        end

        set_cylinder_position_for_location(model, loc_name, axis_name, offset_mm);
        refresh_cylinder_geometry_and_solutions(model, ref_sol_id, comp_sol_id);

        [t_vec, b_uT] = extract_cylinder_data( ...
            model, dataset_tag, ref_sol_id, comp_sol_id, target_path);

        [t_f, b_f] = apply_time_filter(t_vec, b_uT, filter_text);
        if isempty(t_f)
            gui_log(app.logArea, ...
                sprintf('WARN: Filter removed all samples for %s (%s).', ...
                    loc_name, format_cylinder_case_label(h_mm, r_mm, axis_name, offset_mm)));
            skipped_count = skipped_count + 1;
            return;
        end

        write_cylinder_output_file(out_folder, h_mm, r_mm, loc_name, axis_name, offset_mm, t_f, b_f);
        written_count = written_count + 1;
        gui_log(app.logArea, ['OK: ' target_path]);
    catch err
        error_count = error_count + 1;
        gui_log(app.logArea, ...
            sprintf('ERROR [%s, %s]: %s', loc_name, ...
                format_cylinder_case_label(h_mm, r_mm, axis_name, offset_mm), err.message));
    end
end

% --------------------------------------------------------------------------
function label = format_cylinder_case_label(h_mm, r_mm, axis_name, offset_mm)
% format_cylinder_case_label  Human-readable cylinder job descriptor for logging.
    base = sprintf('h=%smm r=%smm', format_offset_value(h_mm), format_offset_value(r_mm));
    if isempty(axis_name)
        label = [base ', Nominal'];
    else
        label = sprintf('%s, Offset%s=%smm', base, upper(axis_name(1)), format_offset_value(offset_mm));
    end
end

% --------------------------------------------------------------------------
function file_path = compose_cylinder_output_file_path(out_folder, h_mm, r_mm, location, axis, val_mm)
% compose_cylinder_output_file_path  Build the cylinder output file path without writing.
    h_str = format_offset_value(h_mm);
    r_str = format_offset_value(r_mm);
    if isempty(axis)
        fname = sprintf('Beddy_Time_Cylinder_h%smm_r%smm_%s.txt', h_str, r_str, location);
    else
        fname = sprintf('Beddy_Time_Cylinder_h%smm_r%smm_%s_Offset_%s_%smm.txt', ...
            h_str, r_str, location, upper(axis(1)), format_offset_value(val_mm));
    end
    file_path = fullfile(out_folder, location, fname);
end

% --------------------------------------------------------------------------
function file_path = write_cylinder_output_file(out_folder, h_mm, r_mm, location, axis, val_mm, t_vec, beddy_uT)
% write_cylinder_output_file  Write a tab-separated cylinder time/Beddy data file.

    if numel(t_vec) ~= numel(beddy_uT)
        error('write_cylinder_output_file:LengthMismatch', ...
            't_vec and beddy_uT must have the same number of elements.');
    end

    loc_folder = fullfile(out_folder, location);
    if ~exist(loc_folder, 'dir')
        mkdir(loc_folder);
    end

    file_path = compose_cylinder_output_file_path(out_folder, h_mm, r_mm, location, axis, val_mm);

    fid = fopen(file_path, 'w');
    if fid < 0
        error('write_cylinder_output_file:OpenFailed', 'Could not open file for writing: %s', file_path);
    end

    cleanup_obj = onCleanup(@() fclose(fid)); %#ok<NASGU>

    fprintf(fid, '%s\tBeddy_uT\n', infer_time_header_label(t_vec));
    for k = 1:numel(t_vec)
        fprintf(fid, '%.16g\t%.16g\n', t_vec(k), beddy_uT(k));
    end
end

% --------------------------------------------------------------------------
function set_cylinder_geometry_params(model, radius_mm, height_mm)
% set_cylinder_geometry_params  Set R_phantom and h_phantom from mm inputs.
    set_single_param(model, 'R_phantom', radius_mm * 1e-3);
    set_single_param(model, 'h_phantom', height_mm * 1e-3);
end

% --------------------------------------------------------------------------
function set_cylinder_position_params(model, x_m, y_m, z_m)
% set_cylinder_position_params  Set h_phantom_offset_* COMSOL parameters in metres.
    set_single_param(model, 'h_phantom_offset_x', x_m);
    set_single_param(model, 'h_phantom_offset_y', y_m);
    set_single_param(model, 'h_phantom_offset_z', z_m);
end

% --------------------------------------------------------------------------
function set_cylinder_position_for_location(model, loc_name, axis_name, offset_mm)
% set_cylinder_position_for_location  Place the cylinder at one canonical location.
    locations = get_point_locations();
    match_idx = [];
    for i = 1:numel(locations)
        if strcmp(locations(i).name, loc_name)
            match_idx = i;
            break;
        end
    end
    if isempty(match_idx)
        error('set_cylinder_position_for_location:UnknownLocation', ...
            'Unknown location "%s".', loc_name);
    end

    loc = locations(match_idx);
    x_m = loc.x;
    y_m = loc.y;
    z_m = loc.z;

    if ~isempty(axis_name) && ~isempty(offset_mm)
        offset_m = offset_mm * 1e-3;
        switch upper(axis_name)
            case 'X'
                x_m = x_m + offset_m;
            case 'Y'
                y_m = y_m + offset_m;
            case 'Z'
                z_m = z_m + offset_m;
            otherwise
                error('set_cylinder_position_for_location:InvalidAxis', ...
                    'Unsupported axis "%s".', axis_name);
        end
    end

    set_cylinder_position_params(model, x_m, y_m, z_m);
end

% --------------------------------------------------------------------------
function refresh_cylinder_geometry_and_solutions(model, ref_sol_id, comp_sol_id)
% refresh_cylinder_geometry_and_solutions  Rebuild geometry and refresh both solutions.
    model.component('comp2').geom('geom2').runPre('fin');

    if ~isempty(strtrim(ref_sol_id))
        model.sol(ref_sol_id).updateSolution;
    end
    if ~isempty(strtrim(comp_sol_id))
        model.sol(comp_sol_id).updateSolution;
    end
end

% --------------------------------------------------------------------------
function dataset_tag = resolve_cylinder_dataset_tag(model, comp_sol_id)
% resolve_cylinder_dataset_tag  Find the comp2 volume dataset for AvVolume extraction.
    dataset_tag = '';
    fallback_comp2_tag = '';

    try
        dataset_tags = cell(model.result.dataset.tags);
    catch
        dataset_tags = {};
    end

    for i = 1:numel(dataset_tags)
        tag = char(dataset_tags{i});
        ds = [];
        try
            ds = model.result.dataset(tag);
        catch
            continue;
        end

        comp_val = '';
        try
            comp_val = char(ds.getString('comp'));
        catch
        end
        if ~strcmp(comp_val, 'comp2')
            continue;
        end

        if isempty(fallback_comp2_tag)
            fallback_comp2_tag = tag;
        end

        for p = 1:2
            prop_names = {'solution', 'sol'};
            try
                sol_val = char(ds.getString(prop_names{p}));
                if strcmp(strtrim(sol_val), comp_sol_id)
                    dataset_tag = tag;
                    return;
                end
            catch
            end
        end
    end

    if ~isempty(fallback_comp2_tag)
        dataset_tag = fallback_comp2_tag;
        return;
    end

    dataset_tag = resolve_solution_dataset_tag(model, comp_sol_id);
end

% --------------------------------------------------------------------------
function [t_vec, beddy_uT] = extract_cylinder_data(model, dataset_tag, ref_sol_id, comp_sol_id, export_path)
% extract_cylinder_data  Extract a cylinder volume-average time trace via AvVolume.

    t_vec = [];
    beddy_uT = [];

    reference_sol_id = strtrim(ref_sol_id);
    if isempty(reference_sol_id)
        reference_sol_id = strtrim(comp_sol_id);
    end

    expr = sprintf(['comp1.genext1((mf.By))-withsol(''%s'',comp1.genext1((mf.By)),setval(t,t))'], ...
        reference_sol_id);

    ensure_cylinder_volume_export(model, dataset_tag, expr, export_path);
    [t_vec, beddy_uT] = read_comsol_point_export(export_path);

    if isempty(t_vec) || isempty(beddy_uT)
        error('extract_cylinder_data:EvaluationFailed', ...
            'COMSOL export returned no valid cylinder volume-average data for dataset %s.', dataset_tag);
    end
end

% --------------------------------------------------------------------------
function ensure_cylinder_volume_export(model, dataset_tag, expr, export_path)
% ensure_cylinder_volume_export  Configure AvVolume + table plot export workflow.

    if exist(export_path, 'file')
        delete(export_path);
    end

    try
        numerical_tags = cell(model.result.numerical.tags);
    catch
        numerical_tags = {};
    end
    if ~any(strcmp(numerical_tags, 'av2'))
        model.result.numerical.create('av2', 'AvVolume');
    end

    model.result.numerical('av2').set('data', dataset_tag);
    model.result.numerical('av2').setIndex('expr', expr, 0);
    model.result.numerical('av2').selection.all;
    model.result.numerical('av2').setIndex('unit', 'uT', 0);

    try
        table_tags = cell(model.result.table.tags);
    catch
        table_tags = {};
    end
    if ~any(strcmp(table_tags, 'tbl25'))
        model.result.table.create('tbl25', 'Table');
        try
            model.result.table('tbl25').comments('Volume Average 2');
        catch
        end
    end

    try
        model.result.table('tbl25').clearTableData;
    catch
    end

    model.result.numerical('av2').set('table', 'tbl25');
    model.result.numerical('av2').setResult;

    try
        result_tags = cell(model.result.tags);
    catch
        result_tags = {};
    end
    if ~any(strcmp(result_tags, 'pg27'))
        model.result.create('pg27', 'PlotGroup1D');
    end
    model.result('pg27').set('data', 'none');

    try
        feature_tags = cell(model.result('pg27').feature.tags);
    catch
        feature_tags = {};
    end
    if ~any(strcmp(feature_tags, 'tblp1'))
        model.result('pg27').create('tblp1', 'Table');
    end

    model.result('pg27').feature('tblp1').set('source', 'table');
    model.result('pg27').feature('tblp1').set('table', 'tbl25');
    model.result('pg27').feature('tblp1').set('linewidth', 'preference');
    model.result('pg27').feature('tblp1').set('markerpos', 'datapoints');
    model.result('pg27').run;

    try
        export_tags = cell(model.result.export.tags);
    catch
        export_tags = {};
    end
    if ~any(strcmp(export_tags, 'plot7'))
        model.result.export.create('plot7', 'pg27', 'tblp1', 'Plot');
    end

    model.result.export('plot7').set('filename', export_path);
    model.result.export('plot7').run;
end
