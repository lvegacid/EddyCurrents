function comsol_analyzer_gui()
% comsol_analyzer_gui  GUI principal para COMSOL Analyzer.
%
% Crea una interfaz gráfica programática (uifigure) que permite:
%   - Seleccionar un archivo .mph mediante diálogo o ruta manual
%   - Seleccionar un directorio de salida
%   - Descubrir y seleccionar datasets del modelo COMSOL cargado
%   - Ejecutar la extracción BFOV para los datasets seleccionados
%
% Uso:
%   comsol_analyzer_gui()
%
% Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1–2.6, 4.1, 4.5, 6.3–6.5

% -------------------------------------------------------------------------
% Task 8.1 — Crear figura y controles base
% -------------------------------------------------------------------------

fig = uifigure('Name', 'COMSOL Analyzer', ...
               'Position', [100 60 760 780], ...
               'Resize', 'on', ...
               'AutoResizeChildren', 'off');
fig.CloseRequestFcn = @closeMainFigure;

prefGroup = 'ComsolAnalyzer';
lastMphPath = getpref(prefGroup, 'LastMphPath', '');
lastMphDir = getpref(prefGroup, 'LastMphDir', '');
lastOutputDir = getpref(prefGroup, 'LastOutputDir', '');

% Estado compartido almacenado en UserData de la figura
state.model    = [];      % objeto modelo COMSOL cargado
state.datasets = [];      % struct array con .tag y .label
state.connection = [];    % estado de conexion LiveLink
state.isClosing = false;  % evita callbacks durante el cierre
state.childDialogs = {};  % dialogos hijos abiertos desde la GUI
state.heartbeatTimer = []; % timer de keep-alive durante extracciones largas
fig.UserData   = state;

% --- Panel: LiveLink Connection ---
btnCheckConnection = uibutton(fig, 'push', ...
    'Text', 'Check / Connect LiveLink', ...
    'Position', [20 520 170 26], ...
    'FontWeight', 'bold');

lblConnection = uilabel(fig, 'Text', 'LiveLink connection status:', ...
    'Position', [210 522 155 22], 'FontWeight', 'bold');

connectionStatusLabel = uilabel(fig, ...
    'Text', 'Unknown', ...
    'Position', [370 522 310 22], ...
    'FontWeight', 'bold', ...
    'FontColor', [0.45 0.45 0.45]);

% --- Panel: MPH File ---
lblMph = uilabel(fig, 'Text', 'MPH File:', ...
    'Position', [20 480 80 22], 'FontWeight', 'bold');

mphField = uieditfield(fig, 'text', ...
    'Position', [105 480 460 22], ...
    'Placeholder', 'Ruta al archivo .mph...', ...
    'Value', lastMphPath);

btnBrowseMph = uibutton(fig, 'push', ...
    'Text', 'Browse MPH', ...
    'Position', [575 480 105 22]);

% --- Panel: Output Directory ---
lblOutput = uilabel(fig, 'Text', 'Output Dir:', ...
    'Position', [20 445 80 22], 'FontWeight', 'bold');

outputField = uieditfield(fig, 'text', ...
    'Position', [105 445 460 22], ...
    'Placeholder', 'Directorio de salida...', ...
    'Value', lastOutputDir);

btnBrowseOut = uibutton(fig, 'push', ...
    'Text', 'Browse Output', ...
    'Position', [575 445 105 22]);

% --- Panel: FOV Info (texto libre para postproceso Python) ---
lblFov = uilabel(fig, 'Text', 'FOV Info:', ...
    'Position', [20 410 80 22], 'FontWeight', 'bold');

fovInfoField = uieditfield(fig, 'text', ...
    'Position', [105 410 575 22], ...
    'Placeholder', 'Ej: Sphere(340 mm)');

% --- Panel: Datasets ---
lblDatasets = uilabel(fig, 'Text', 'Datasets disponibles:', ...
    'Position', [20 380 200 22], 'FontWeight', 'bold');

datasetList = uilistbox(fig, ...
    'Position', [20 230 660 145], ...
    'Items', {}, ...
    'MultiSelect', 'on');

% --- Botón Run ---
btnRun = uibutton(fig, 'push', ...
    'Text', 'Run Extraction', ...
    'Position', [20 205 150 30], ...
    'Enable', 'off', ...
    'FontWeight', 'bold');

% --- Opciones de salida ---
chkBfov3D = uicheckbox(fig, ...
    'Text', 'B_FOV 3D Plot', ...
    'Position', [20 173 220 22], ...
    'Value', true);

chkBfovHist = uicheckbox(fig, ...
    'Text', 'B_FOV Histogram', ...
    'Position', [20 149 220 22], ...
    'Value', true);

chkBfovCoord = uicheckbox(fig, ...
    'Text', 'B_FOV Custom Coordinates', ...
    'Position', [20 125 250 22], ...
    'Value', false);

chkMagnets3D = uicheckbox(fig, ...
    'Text', 'Magnets 3D Plot', ...
    'Position', [20 101 220 22], ...
    'Value', false);

chkMagnetsHist = uicheckbox(fig, ...
    'Text', 'Magnets Histogram', ...
    'Position', [20 77 220 22], ...
    'Value', false);

% --- Panel: Log ---
lblLog = uilabel(fig, 'Text', 'Log:', ...
    'Position', [20 88 60 22], 'FontWeight', 'bold');

btnCopyLog = uibutton(fig, 'push', ...
    'Text', 'Copy Log', ...
    'Position', [575 88 105 22]);

logArea = uitextarea(fig, ...
    'Position', [20 20 660 65], ...
    'Editable', 'on', ...
    'Value', '');

% -------------------------------------------------------------------------
% Callback "Check / Connect LiveLink"
% -------------------------------------------------------------------------
btnCheckConnection.ButtonPushedFcn = @(~,~) checkConnectionCallback();

% -------------------------------------------------------------------------
% Task 8.3 — Callback "Browse MPH"
% -------------------------------------------------------------------------
btnBrowseMph.ButtonPushedFcn = @(~,~) browseMphCallback();

% -------------------------------------------------------------------------
% Task 8.4 — Validación manual de ruta MPH (foco perdido / Enter)
% -------------------------------------------------------------------------
mphField.ValueChangedFcn = @(src,~) validateMphPath(src.Value);

% -------------------------------------------------------------------------
% Task 8.7 — Callback "Browse Output"
% -------------------------------------------------------------------------
btnBrowseOut.ButtonPushedFcn = @(~,~) browseOutputCallback();

% -------------------------------------------------------------------------
% Task 8.8 — Callback "Run Extraction"
% -------------------------------------------------------------------------
btnRun.ButtonPushedFcn = @(~,~) runExtractionCallback();

% -------------------------------------------------------------------------
% Callback "Copy Log"
% -------------------------------------------------------------------------
btnCopyLog.ButtonPushedFcn = @(~,~) copyLogCallback();

% Refrescar estado del botón Run cuando cambian opciones
chkBfov3D.ValueChangedFcn = @(~,~) updateRunButtonState();
chkBfovHist.ValueChangedFcn = @(~,~) updateRunButtonState();
chkBfovCoord.ValueChangedFcn = @(~,~) updateRunButtonState();
chkMagnets3D.ValueChangedFcn = @(~,~) updateRunButtonState();
chkMagnetsHist.ValueChangedFcn = @(~,~) updateRunButtonState();

% Layout responsivo para log y datasets
fig.SizeChangedFcn = @(~,~) layoutControls();

% =========================================================================
% Funciones internas (closures)
% =========================================================================

    function layoutControls()
        if isFigureClosing()
            return;
        end

        p = fig.Position;
        figW = p(3);
        figH = p(4);

        left = 20;
        right = 20;
        top = 18;
        bottom = 20;

        browseW = 105;
        labelW = 80;
        gap = 10;

        xLabel = left;
        xField = 105;
        xBrowse = figW - right - browseW;
        fieldW = max(140, xBrowse - gap - xField);
        wideW = max(240, figW - left - right);

        yConn = figH - top - 26;
        yMph = yConn - 42;
        yOut = yMph - 35;
        yFov = yOut - 35;
        yDatasetLabel = yFov - 34;

        % Dataset list: ajustado al numero real de items para evitar espacio muerto.
        nItems = numel(datasetList.Items);
        visibleRows = min(max(nItems, 2), 6);
        desiredDatasetH = 18 + visibleRows * 22;
        desiredDatasetH = min(max(desiredDatasetH, 62), 170);

        minLogH = 190;
        minRunY = bottom + minLogH + 165;
        datasetTop = yDatasetLabel - 6;
        maxDatasetHBySpace = max(60, datasetTop - (minRunY + 38));
        datasetH = min(desiredDatasetH, maxDatasetHBySpace);
        datasetY = datasetTop - datasetH;

        runY = datasetY - 38;
        chk3DY = runY - 32;
        chkHistY = chk3DY - 24;
        chkCoordY = chkHistY - 24;
        chkMag3DY = chkCoordY - 24;
        chkMagHistY = chkMag3DY - 24;
        logLabelY = chkMagHistY - 34;
        logH = max(minLogH, logLabelY - 3 - bottom);

        btnCheckConnection.Position = [left yConn 170 26];
        lblConnection.Position = [left + 190 yConn + 2 155 22];
        connectionStatusLabel.Position = [left + 350 yConn + 2 max(120, figW - right - (left + 350)) 22];

        lblMph.Position = [xLabel yMph labelW 22];
        mphField.Position = [xField yMph fieldW 22];
        btnBrowseMph.Position = [xBrowse yMph browseW 22];

        lblOutput.Position = [xLabel yOut labelW 22];
        outputField.Position = [xField yOut fieldW 22];
        btnBrowseOut.Position = [xBrowse yOut browseW 22];

        lblFov.Position = [xLabel yFov labelW 22];
        fovInfoField.Position = [xField yFov max(240, figW - right - xField) 22];

        lblDatasets.Position = [left yDatasetLabel 260 22];
        datasetList.Position = [left datasetY wideW datasetH];

        btnRun.Position = [left runY 150 30];
        chkBfov3D.Position = [left chk3DY 220 22];
        chkBfovHist.Position = [left chkHistY 220 22];
        chkBfovCoord.Position = [left chkCoordY 250 22];
        chkMagnets3D.Position = [left chkMag3DY 220 22];
        chkMagnetsHist.Position = [left chkMagHistY 220 22];

        lblLog.Position = [left logLabelY 60 22];
        btnCopyLog.Position = [xBrowse logLabelY browseW 22];
        logArea.Position = [left bottom wideW logH];
    end

    function clearLoadedModel()
        if ~isvalid(fig)
            return;
        end

        s = fig.UserData;
        s.model = [];
        s.datasets = [];
        fig.UserData = s;
        populateDatasets([]);
        updateRunButtonState();
    end

    function updateRunButtonState()
        if isFigureClosing() || ~isvalid(btnRun)
            return;
        end

        s = fig.UserData;
        hasModel = ~isempty(s.model);
        hasDatasets = ~isempty(s.datasets);
        hasOutputOption = logical(chkBfov3D.Value) || logical(chkBfovHist.Value) || ...
            logical(chkBfovCoord.Value) || logical(chkMagnets3D.Value) || logical(chkMagnetsHist.Value);

        if hasModel && hasDatasets && hasOutputOption
            btnRun.Enable = 'on';
        else
            btnRun.Enable = 'off';
        end
    end

    function updateConnectionIndicator(status, shouldLog)
        if nargin < 2
            shouldLog = false;
        end

        if isFigureClosing() || ~isvalid(connectionStatusLabel)
            return;
        end

        if status.connected
            connectionStatusLabel.Text = ['Connected - ' status.message];
            connectionStatusLabel.FontColor = [0.00 0.45 0.20];
        else
            connectionStatusLabel.Text = ['Disconnected - ' status.message];
            connectionStatusLabel.FontColor = [0.75 0.10 0.10];
        end

        s = fig.UserData;
        s.connection = status;
        fig.UserData = s;

        if shouldLog
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            if status.connected
                appendLog('INFO', ts, '', ['Estado LiveLink: ' status.message]);
            else
                appendLog('WARN', ts, '', ['Estado LiveLink: ' status.message]);
                if ~isempty(status.detail)
                    appendLog('WARN', ts, '', ['Detalle LiveLink: ' status.detail]);
                end
            end
        end
    end

    function status = refreshConnectionStatus(action, shouldLog)
        if nargin < 1 || isempty(action)
            action = 'status';
        end
        if nargin < 2
            shouldLog = false;
        end

        status = comsol_livelink_connection(action);
        updateConnectionIndicator(status, shouldLog);
    end

    % --- Añadir línea al log ---
    function appendLog(level, timestamp, datasetTag, message)
        if isFigureClosing() || ~isvalid(logArea)
            return;
        end

        if nargin == 1
            % Llamada simple: appendLog('texto')
            line = level;
        else
            line = sprintf('[%s] [%s] [%s] %s', timestamp, level, datasetTag, message);
        end
        current = logArea.Value;
        if ischar(current)
            current = {current};
        elseif isstring(current)
            current = cellstr(current);
        end
        if isempty(current) || (numel(current) == 1 && isempty(current{1}))
            logArea.Value = {line};
        else
            logArea.Value = [current; {line}];
        end
        % Scroll al final
        scroll(logArea, 'bottom');
        drawnow;
    end

    % --- Poblar lista de datasets ---
    function populateDatasets(datasets)
        if isFigureClosing() || ~isvalid(datasetList)
            return;
        end

        s = fig.UserData;
        s.datasets = datasets;
        fig.UserData = s;

        if isempty(datasets)
            datasetList.Items = {};
            datasetList.Value = {};
            layoutControls();
            updateRunButtonState();
            return;
        end

        items = cell(numel(datasets), 1);
        for k = 1:numel(datasets)
            items{k} = sprintf('%s: %s', datasets(k).tag, datasets(k).label);
        end
        datasetList.Items = items;
        datasetList.Value = items;
        layoutControls();
        updateRunButtonState();
    end

    % --- Cargar modelo y datasets desde una ruta MPH ---
    function loadModelFromPath(mphPath)
        % Limpiar estado previo
        clearLoadedModel();

        status = refreshConnectionStatus('status', true);
        if ~status.connected
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ...
                'LiveLink reporta desconexión. Se intentará cargar el modelo igualmente.');
        end

        % Cargar modelo
        try
            mdl = load_model(mphPath);
        catch err
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', err.message);
            return;
        end

        % Obtener datasets
        try
            datasets = get_datasets(mdl);
        catch err
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', err.message);
            return;
        end

        % Guardar modelo en estado
        s = fig.UserData;
        s.model = mdl;
        fig.UserData = s;

        if isempty(datasets)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', 'No se encontraron datasets en el modelo.');
            updateRunButtonState();
        else
            populateDatasets(datasets);
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('INFO', ts, '', sprintf('Modelo cargado. %d dataset(s) encontrado(s).', numel(datasets)));
            updateRunButtonState();
        end
    end

    % -----------------------------------------------------------------
    % Callback de estado / conexion LiveLink
    % -----------------------------------------------------------------
    function checkConnectionCallback()
        if isFigureClosing()
            return;
        end

        refreshConnectionStatus('connect', true);
        updateRunButtonState();
    end

    % -----------------------------------------------------------------
    % Task 8.3 — Browse MPH callback
    % -----------------------------------------------------------------
    function browseMphCallback()
        if isFigureClosing()
            return;
        end

        % Bring figure to front and flush event queue before opening dialog
        figure(fig);
        drawnow;

        startPath = '';
        currentMph = strtrim(mphField.Value);
        if ~isempty(currentMph)
            if isfile(currentMph)
                startPath = currentMph;
            else
                curDir = fileparts(currentMph);
                if ~isempty(curDir) && isfolder(curDir)
                    startPath = curDir;
                end
            end
        end
        if isempty(startPath) && ~isempty(lastMphPath) && isfile(lastMphPath)
            startPath = lastMphPath;
        end
        if isempty(startPath) && ~isempty(lastMphDir) && isfolder(lastMphDir)
            startPath = lastMphDir;
        end

        [fname, fpath] = uigetfile({'*.mph','COMSOL Model (*.mph)'}, ...
                                   'Seleccionar archivo MPH', startPath);
        % Restore focus to uifigure after dialog closes
        figure(fig);
        drawnow;
        if isequal(fname, 0)
            return;  % usuario canceló
        end
        fullPath = fullfile(fpath, fname);
        setpref(prefGroup, 'LastMphPath', fullPath);
        setpref(prefGroup, 'LastMphDir', fpath);
        lastMphPath = fullPath;
        lastMphDir = fpath;
        mphField.Value = fullPath;
        loadModelFromPath(fullPath);
    end

    % -----------------------------------------------------------------
    % Task 8.4 — Validación manual de ruta MPH
    % -----------------------------------------------------------------
    function validateMphPath(mphPath)
        if isFigureClosing()
            return;
        end

        mphPath = strtrim(mphPath);
        if isempty(mphPath)
            return;
        end

        [~, ~, ext] = fileparts(mphPath);
        if ~strcmpi(ext, '.mph')
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', ...
                sprintf('Ruta inválida: la extensión "%s" no es .mph.', ext));
            btnRun.Enable = 'off';
            return;
        end

        if ~isfile(mphPath)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', ...
                sprintf('Ruta inválida: el archivo no existe: %s', mphPath));
            btnRun.Enable = 'off';
            return;
        end

        % Ruta válida — cargar modelo
        setpref(prefGroup, 'LastMphPath', mphPath);
        mphDir = fileparts(mphPath);
        if ~isempty(mphDir)
            setpref(prefGroup, 'LastMphDir', mphDir);
            lastMphDir = mphDir;
        end
        lastMphPath = mphPath;
        loadModelFromPath(mphPath);
    end

    % -----------------------------------------------------------------
    % Task 8.7 — Browse Output callback
    % -----------------------------------------------------------------
    function browseOutputCallback()
        if isFigureClosing()
            return;
        end

        figure(fig);
        drawnow;

        startDir = '';
        currentOut = strtrim(outputField.Value);
        if ~isempty(currentOut) && isfolder(currentOut)
            startDir = currentOut;
        elseif ~isempty(lastOutputDir) && isfolder(lastOutputDir)
            startDir = lastOutputDir;
        end

        if isempty(startDir)
            selDir = uigetdir('', 'Seleccionar directorio de salida');
        else
            selDir = uigetdir(startDir, 'Seleccionar directorio de salida');
        end
        figure(fig);
        drawnow;
        if isequal(selDir, 0)
            return;  % usuario canceló
        end
        setpref(prefGroup, 'LastOutputDir', selDir);
        lastOutputDir = selDir;
        outputField.Value = selDir;
    end

    % -----------------------------------------------------------------
    % Task 8.8 — Run Extraction callback
    % -----------------------------------------------------------------
    function runExtractionCallback()
        if isFigureClosing()
            return;
        end

        status = refreshConnectionStatus('status', false);
        if ~status.connected
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ...
                'LiveLink no esta conectado. Verifica COMSOL with MATLAB y vuelve a intentar.');
            updateRunButtonState();
            return;
        end

        % Verificar selección de datasets
        selectedItems = datasetList.Value;
        if isempty(selectedItems)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ...
                'Debe seleccionar al menos un dataset antes de ejecutar la extracción.');
            return;
        end

        % Verificar directorio de salida
        outputDir = strtrim(outputField.Value);
        if isempty(outputDir)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ...
                'Debe especificar un directorio de salida.');
            return;
        end

        if isfolder(outputDir)
            setpref(prefGroup, 'LastOutputDir', outputDir);
            lastOutputDir = outputDir;
        end

        % Obtener modelo y datasets del estado
        s = fig.UserData;
        mdl      = s.model;
        allDsets = s.datasets;

        if isempty(mdl)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', 'No hay modelo cargado.');
            return;
        end

        % Mapear items seleccionados → structs de dataset
        if ischar(selectedItems)
            selectedItems = {selectedItems};
        end
        selectedDatasets = struct('tag', {}, 'label', {}, 'shortLabel', {});
        for k = 1:numel(selectedItems)
            item = selectedItems{k};
            % Formato: "<tag>: <label>"
            colonIdx = strfind(item, ': ');
            if ~isempty(colonIdx)
                tag = strtrim(item(1:colonIdx(1)-1));
            else
                tag = strtrim(item);
            end
            % Buscar en allDsets
            for j = 1:numel(allDsets)
                if strcmp(allDsets(j).tag, tag)
                    selectedDatasets(end+1) = allDsets(j); %#ok<AGROW>
                    break;
                end
            end
        end

        if isempty(selectedDatasets)
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', 'No se pudieron resolver los datasets seleccionados.');
            return;
        end

        % Derivar modelName desde la ruta MPH
        mphPath = strtrim(mphField.Value);
        [~, modelName, ~] = fileparts(mphPath);

        [canWriteOutput, outputMessage] = validate_output_directory(outputDir, modelName);
        if ~canWriteOutput
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', outputMessage);
            appendLog('WARN', ts, '', ...
                'Selecciona una carpeta local con permisos de escritura y vuelve a ejecutar.');
            return;
        end

        % Metadata para postproceso Python
        fovInfo = strtrim(fovInfoField.Value);
        if isempty(fovInfo)
            fovInfo = 'N/A';
        end

        % Opciones de salida seleccionadas
        options = struct();
        options.enable3DPlot = logical(chkBfov3D.Value);
        options.enableHistogram = logical(chkBfovHist.Value);
        options.enableCustomCoordinates = logical(chkBfovCoord.Value);
        options.enableMagnets3DPlot = logical(chkMagnets3D.Value);
        options.enableMagnetsHistogram = logical(chkMagnetsHist.Value);

        if ~options.enable3DPlot && ~options.enableHistogram && ~options.enableCustomCoordinates && ...
           ~options.enableMagnets3DPlot && ~options.enableMagnetsHistogram
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ...
                ['Debe seleccionar al menos una opción de salida ' ...
                 '(B_FOV 3D, B_FOV Histogram, B_FOV Custom Coordinates, Magnets 3D o Magnets Histogram).']);
            return;
        end

        if options.enableHistogram
            [okBins, histBins] = ask_histogram_bins();
            if ~okBins
                ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
                appendLog('INFO', ts, '', 'Extracción cancelada por el usuario (configuración de histogram bins).');
                return;
            end
            options.histBins = histBins;
        else
            options.histBins = getpref('ComsolAnalyzer', 'HistogramBins', 100);
        end

        if options.enableCustomCoordinates
            [okCoord, coordCfg] = ask_custom_coordinates_config();
            if ~okCoord
                ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
                appendLog('INFO', ts, '', 'Extracción cancelada por el usuario (configuración de coordenadas).');
                return;
            end
            options.coordConfig = coordCfg;
        else
            options.coordConfig = struct('model', 'Spherical coordinates', ...
                'nTheta', getpref('ComsolAnalyzer', 'Coord_nTheta', 100), ...
                'nPhi',   getpref('ComsolAnalyzer', 'Coord_nPhi', 100), ...
                'R',      getpref('ComsolAnalyzer', 'Coord_R', 0.1));
        end

        if options.enableMagnetsHistogram
            [okMagnetsCfg, magnetsHistBins, magnetsStepPercent, magnetsBr] = ask_magnets_histogram_config();
            if ~okMagnetsCfg
                ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
                appendLog('INFO', ts, '', 'Extracción cancelada por el usuario (configuración de Magnets histogram).');
                return;
            end
            options.magnetsHistBins = magnetsHistBins;
            options.magnetsStepPercent = magnetsStepPercent;
            options.magnetsBr = magnetsBr;
        else
            options.magnetsHistBins = getpref('ComsolAnalyzer', 'MagnetsHistogramBins', 100);
            options.magnetsStepPercent = getpref('ComsolAnalyzer', 'MagnetsHistogramStepPercent', 2);
            options.magnetsBr = getpref('ComsolAnalyzer', 'MagnetsHistogramBr', 1.4);
        end

        % Deshabilitar Run durante la extracción
        btnRun.Enable = 'off';
        extractionStartedAt = tic;
        heartbeatTimer = startExtractionHeartbeat();
        drawnow;

        % Callbacks para extraction_controller
        logFn      = @(level, ts, tag, msg) appendLog(level, ts, tag, msg);
        progressFn = @(current, total) appendLog('INFO', ...
            datestr(now, 'yyyy-mm-dd HH:MM:SS'), '', ...
            sprintf('Progreso: %d / %d datasets procesados.', current, total));

        % Ejecutar extracción
        try
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('INFO', ts, '', sprintf('Iniciando extracción de %d dataset(s).', numel(selectedDatasets)));
            summary = extraction_controller(mdl, selectedDatasets, outputDir, ...
                                            modelName, logFn, progressFn, fovInfo, options);
        catch err
            stopExtractionHeartbeat(heartbeatTimer);
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', ...
                sprintf('Error inesperado en extraction_controller: %s', err.message));
            updateRunButtonState();
            return;
        end

        stopExtractionHeartbeat(heartbeatTimer);

        % Mostrar resumen final
        ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
        appendLog('INFO', ts, '', '--- Resumen de extracción ---');
        appendLog('INFO', ts, '', sprintf('  Datasets OK:    %d', summary.nOK));
        appendLog('INFO', ts, '', sprintf('  Datasets error: %d', summary.nError));
        appendLog('INFO', ts, '', sprintf('  Directorio:     %s', summary.outputDir));
        appendLog('INFO', ts, '', sprintf('  Tiempo total:   %s', formatElapsedTime(toc(extractionStartedAt))));

        % Rehabilitar Run
        updateRunButtonState();
    end

    function heartbeatTimer = startExtractionHeartbeat()
        heartbeatTimer = [];
        if isFigureClosing()
            return;
        end

        stopExtractionHeartbeat([]);

        startedAt = tic;
        heartbeatTimer = timer( ...
            'ExecutionMode', 'fixedSpacing', ...
            'Period', 60, ...
            'BusyMode', 'drop', ...
            'TimerFcn', @onHeartbeatTick, ...
            'StopFcn', @onHeartbeatStop, ...
            'ErrorFcn', @onHeartbeatError);

        s = fig.UserData;
        s.heartbeatTimer = heartbeatTimer;
        fig.UserData = s;

        start(heartbeatTimer);

        function onHeartbeatTick(~, ~)
            if isFigureClosing() || ~isvalid(logArea)
                return;
            end

            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('INFO', ts, '', ...
                ['Extracción en curso. La aplicación sigue activa ' ...
                 '(tiempo transcurrido: ' formatElapsedTime(toc(startedAt)) ').']);
        end

        function onHeartbeatStop(src, ~)
            clearHeartbeatReference(src);
        end

        function onHeartbeatError(src, evt)
            clearHeartbeatReference(src);
            if isFigureClosing() || ~isvalid(logArea)
                return;
            end

            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('WARN', ts, '', ['Heartbeat de extracción detenido: ' evt.Data.Message]);
        end
    end

    function stopExtractionHeartbeat(heartbeatTimer)
        timerToStop = heartbeatTimer;
        if isempty(timerToStop) && isvalid(fig)
            s = fig.UserData;
            if isfield(s, 'heartbeatTimer')
                timerToStop = s.heartbeatTimer;
            end
        end

        if isempty(timerToStop)
            clearHeartbeatReference([]);
            return;
        end

        try
            if isvalid(timerToStop)
                stop(timerToStop);
            end
        catch
        end

        try
            if isvalid(timerToStop)
                delete(timerToStop);
            end
        catch
        end

        clearHeartbeatReference(timerToStop);
    end

    function clearHeartbeatReference(timerHandle)
        if ~isvalid(fig)
            return;
        end

        s = fig.UserData;
        if ~isfield(s, 'heartbeatTimer') || isempty(s.heartbeatTimer)
            return;
        end

        if isempty(timerHandle)
            s.heartbeatTimer = [];
            fig.UserData = s;
            return;
        end

        try
            sameTimer = isvalid(timerHandle) && isvalid(s.heartbeatTimer) && timerHandle == s.heartbeatTimer;
        catch
            sameTimer = false;
        end

        if sameTimer
            s.heartbeatTimer = [];
            fig.UserData = s;
        end
    end

    function text = formatElapsedTime(secondsElapsed)
        totalSeconds = max(0, floor(secondsElapsed));
        hoursPart = floor(totalSeconds / 3600);
        minutesPart = floor(mod(totalSeconds, 3600) / 60);
        secondsPart = mod(totalSeconds, 60);

        if hoursPart > 0
            text = sprintf('%02dh %02dm %02ds', hoursPart, minutesPart, secondsPart);
        else
            text = sprintf('%02dm %02ds', minutesPart, secondsPart);
        end
    end

    function copyLogCallback()
        if isFigureClosing()
            return;
        end

        lines = logArea.Value;

        if ischar(lines)
            lines = {lines};
        elseif isstring(lines)
            lines = cellstr(lines);
        end

        if isempty(lines)
            payload = '';
        else
            payload = strjoin(lines, newline);
        end

        try
            clipboard('copy', payload);
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('INFO', ts, '', 'Log copiado al portapapeles.');
        catch err
            ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
            appendLog('ERROR', ts, '', ['No se pudo copiar el log: ' err.message]);
        end
    end

    function [ok, bins] = ask_histogram_bins()
        ok = false;
        bins = getpref('ComsolAnalyzer', 'HistogramBins', 100);

        answer = inputdlg({'Number of bins:'}, 'B_FOV Histogram', 1, {num2str(bins)});
        if isempty(answer)
            return;
        end

        value = str2double(strtrim(answer{1}));
        if isnan(value) || ~isfinite(value) || value < 1 || floor(value) ~= value
            uialert(fig, 'El valor de bins debe ser un entero positivo.', 'Valor inválido');
            return;
        end

        bins = value;
        setpref('ComsolAnalyzer', 'HistogramBins', bins);
        ok = true;
    end

    function [ok, cfg] = ask_custom_coordinates_config()
        ok = false;
        cfg = struct('model', 'Spherical coordinates', ...
            'source', 'spherical', ...
            'nTheta', getpref('ComsolAnalyzer', 'Coord_nTheta', 100), ...
            'nPhi',   getpref('ComsolAnalyzer', 'Coord_nPhi', 100), ...
            'R',      getpref('ComsolAnalyzer', 'Coord_R', 0.1), ...
            'coordFilePath', '', ...
            'coordColumns', [1 2 3], ...
            'sourceFilePath', '');

        dlg = uifigure('Name', 'B_FOV Custom Coordinates', ...
            'Position', [280 180 480 350], ...
            'WindowStyle', 'modal', ...
            'Resize', 'off');
        dlg.Tag = 'ComsolAnalyzerChildDialog';
        registerChildDialog(dlg);

        uilabel(dlg, 'Text', 'Model selection', 'Position', [20 298 130 22], 'FontWeight', 'bold');
        modelDrop = uidropdown(dlg, ...
            'Items', {'Spherical coordinates', 'From file'}, ...
            'Value', 'Spherical coordinates', ...
            'Position', [160 298 260 22]);

        uilabel(dlg, 'Text', 'n_theta', 'Position', [20 246 80 22], 'FontWeight', 'bold');
        nThetaField = uieditfield(dlg, 'numeric', ...
            'Position', [160 246 260 22], ...
            'RoundFractionalValues', 'on', ...
            'Limits', [1 Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', cfg.nTheta);

        uilabel(dlg, 'Text', 'n_phi', 'Position', [20 210 80 22], 'FontWeight', 'bold');
        nPhiField = uieditfield(dlg, 'numeric', ...
            'Position', [160 210 260 22], ...
            'RoundFractionalValues', 'on', ...
            'Limits', [1 Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', cfg.nPhi);

        uilabel(dlg, 'Text', 'R [m]', 'Position', [20 174 80 22], 'FontWeight', 'bold');
        rField = uieditfield(dlg, 'numeric', ...
            'Position', [160 174 260 22], ...
            'Limits', [eps Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', cfg.R);

        uilabel(dlg, 'Text', 'Coordinate file', 'Position', [20 128 130 22], 'FontWeight', 'bold');
        filePathField = uieditfield(dlg, 'text', ...
            'Position', [160 128 180 22], ...
            'Placeholder', 'Select a .txt file...');
        btnBrowseFile = uibutton(dlg, 'push', ...
            'Text', 'Browse', ...
            'Position', [350 128 70 22], ...
            'ButtonPushedFcn', @browseCoordinateFile);

        uilabel(dlg, 'Text', 'Columns x / y / z', 'Position', [20 92 130 22], 'FontWeight', 'bold');
        xColField = uieditfield(dlg, 'numeric', ...
            'Position', [160 92 54 22], ...
            'RoundFractionalValues', 'on', ...
            'Limits', [1 Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', 1);
        yColField = uieditfield(dlg, 'numeric', ...
            'Position', [220 92 54 22], ...
            'RoundFractionalValues', 'on', ...
            'Limits', [1 Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', 2);
        zColField = uieditfield(dlg, 'numeric', ...
            'Position', [280 92 54 22], ...
            'RoundFractionalValues', 'on', ...
            'Limits', [1 Inf], ...
            'LowerLimitInclusive', true, ...
            'Value', 3);
        fileInfoLabel = uilabel(dlg, 'Text', '', ...
            'Position', [20 56 420 20], ...
            'FontColor', [0.35 0.35 0.35]);

        btnOk = uibutton(dlg, 'push', ...
            'Text', 'OK', ...
            'Position', [160 16 80 30]);
        btnCancel = uibutton(dlg, 'push', ...
            'Text', 'Cancel', ...
            'Position', [260 16 80 30]);

        btnOk.ButtonPushedFcn = @on_ok;
        btnCancel.ButtonPushedFcn = @on_cancel;
        modelDrop.ValueChangedFcn = @(~,~) updateDialogMode();
        dlg.CloseRequestFcn = @on_cancel;

        updateDialogMode();

        uiwait(dlg);

        function updateDialogMode()
            isFileMode = strcmp(modelDrop.Value, 'From file');

            if isFileMode
                nThetaField.Enable = 'off';
                nPhiField.Enable = 'off';
                rField.Enable = 'off';
                filePathField.Enable = 'on';
                btnBrowseFile.Enable = 'on';
                xColField.Enable = 'on';
                yColField.Enable = 'on';
                zColField.Enable = 'on';
            else
                nThetaField.Enable = 'on';
                nPhiField.Enable = 'on';
                rField.Enable = 'on';
                filePathField.Enable = 'off';
                btnBrowseFile.Enable = 'off';
                xColField.Enable = 'off';
                yColField.Enable = 'off';
                zColField.Enable = 'off';
            end

            if isFileMode
                if isempty(strtrim(filePathField.Value))
                    fileInfoLabel.Text = 'Select a .txt file with at least 3 numeric columns.';
                end
            else
                fileInfoLabel.Text = '';
            end
        end

        function browseCoordinateFile(~, ~)
            startDir = '';
            currentPath = strtrim(filePathField.Value);
            if ~isempty(currentPath)
                currentDir = fileparts(currentPath);
                if ~isempty(currentDir) && isfolder(currentDir)
                    startDir = currentDir;
                end
            end

            [fname, fpath] = uigetfile({'*.txt', 'Text files (*.txt)'}, ...
                'Select coordinate file', startDir);
            if isequal(fname, 0)
                return;
            end

            fullPath = fullfile(fpath, fname);
            filePathField.Value = fullPath;

            try
                data = readmatrix(fullPath, 'FileType', 'text', 'CommentStyle', '%');
            catch err
                fileInfoLabel.Text = '';
                uialert(dlg, ['No se pudo leer el archivo de coordenadas: ' err.message], 'Archivo inválido');
                return;
            end

            if isempty(data) || size(data, 2) < 3
                fileInfoLabel.Text = '';
                uialert(dlg, 'El archivo .txt debe contener al menos 3 columnas.', 'Archivo inválido');
                return;
            end

            if size(data, 2) > 3
                msg = sprintf('El archivo tiene %d columnas. Se usaran las columnas seleccionadas.', size(data, 2));
                fileInfoLabel.Text = msg;
                uialert(dlg, msg, 'Archivo con columnas extra');
            else
                fileInfoLabel.Text = sprintf('Archivo cargado con %d columna(s).', size(data, 2));
            end

            xColField.Value = 1;
            yColField.Value = 2;
            zColField.Value = 3;
        end

        function on_ok(~, ~)
            candidateCfg = struct('model', modelDrop.Value, ...
                'source', 'spherical', ...
                'nTheta', floor(nThetaField.Value), ...
                'nPhi', floor(nPhiField.Value), ...
                'R', rField.Value, ...
                'coordFilePath', '', ...
                'coordColumns', [1 2 3], ...
                'sourceFilePath', '');

            if strcmp(modelDrop.Value, 'From file')
                sourceFilePath = strtrim(filePathField.Value);
                coordColumns = [floor(xColField.Value), floor(yColField.Value), floor(zColField.Value)];

                if isempty(sourceFilePath) || ~isfile(sourceFilePath)
                    uialert(dlg, 'Selecciona un archivo .txt de coordenadas válido.', 'Archivo inválido');
                    return;
                end

                if any(coordColumns < 1) || numel(unique(coordColumns)) ~= 3
                    uialert(dlg, 'Las columnas de coordenadas deben ser enteros positivos y distintos.', 'Columnas inválidas');
                    return;
                end

                try
                    data = readmatrix(sourceFilePath, 'FileType', 'text', 'CommentStyle', '%');
                catch err
                    uialert(dlg, ['No se pudo leer el archivo de coordenadas: ' err.message], 'Archivo inválido');
                    return;
                end

                if isempty(data) || size(data, 2) < 3
                    uialert(dlg, 'El archivo .txt debe contener al menos 3 columnas.', 'Archivo inválido');
                    return;
                end

                if size(data, 2) < max(coordColumns)
                    uialert(dlg, sprintf('El archivo solo contiene %d columnas y se solicitaron las columnas %s.', ...
                        size(data, 2), mat2str(coordColumns)), 'Columnas inválidas');
                    return;
                end

                if size(data, 2) > 3
                    msg = sprintf('El archivo tiene %d columnas. Se usaran las columnas %d, %d y %d.', ...
                        size(data, 2), coordColumns(1), coordColumns(2), coordColumns(3));
                    fileInfoLabel.Text = msg;
                    uialert(dlg, msg, 'Archivo con columnas extra');
                end

                coords = data(:, coordColumns);
                coords = coords(all(isfinite(coords), 2), :);

                if isempty(coords)
                    uialert(dlg, 'No se encontraron coordenadas validas en las columnas seleccionadas.', 'Archivo inválido');
                    return;
                end

                candidateCfg.source = 'file';
                candidateCfg.coordFilePath = sourceFilePath;
                candidateCfg.coordColumns = coordColumns;
                candidateCfg.sourceFilePath = sourceFilePath;

                previewText = sprintf('Preview de coordenadas desde archivo: %s | columnas %d, %d, %d | puntos=%d', ...
                    sourceFilePath, coordColumns(1), coordColumns(2), coordColumns(3), size(coords, 1));
                shouldProceed = preview_custom_coordinate_configuration(candidateCfg, coords, previewText);
                if ~shouldProceed
                    return;
                end

                cfg = candidateCfg;
                ok = true;
                uiresume(dlg);
                unregisterChildDialog(dlg);
                delete(dlg);
                return;
            end

            nTheta = candidateCfg.nTheta;
            nPhi = candidateCfg.nPhi;
            rVal = candidateCfg.R;

            if any([isnan(nTheta), isnan(nPhi), isnan(rVal)]) || ...
               ~isfinite(nTheta) || ~isfinite(nPhi) || ~isfinite(rVal) || ...
               nTheta < 1 || nPhi < 1 || rVal <= 0
                uialert(dlg, 'Completa valores válidos para n_theta, n_phi y R.', 'Valores inválidos');
                return;
            end

            coords = build_spherical_coordinate_matrix(candidateCfg.nTheta, candidateCfg.nPhi, candidateCfg.R);
            previewText = sprintf('Preview del archivo Coordinates generado. nTheta=%d, nPhi=%d, R=%.6f m, puntos=%d', ...
                candidateCfg.nTheta, candidateCfg.nPhi, candidateCfg.R, size(coords, 1));

            shouldProceed = preview_custom_coordinate_configuration(candidateCfg, coords, previewText);
            if ~shouldProceed
                return;
            end

            cfg = candidateCfg;

            setpref('ComsolAnalyzer', 'Coord_nTheta', cfg.nTheta);
            setpref('ComsolAnalyzer', 'Coord_nPhi', cfg.nPhi);
            setpref('ComsolAnalyzer', 'Coord_R', cfg.R);

            ok = true;
            uiresume(dlg);
            unregisterChildDialog(dlg);
            delete(dlg);
        end

        function on_cancel(~, ~)
            ok = false;
            if isvalid(dlg)
                uiresume(dlg);
                unregisterChildDialog(dlg);
                delete(dlg);
            end
        end
    end

    function [ok, bins, stepPercent, br] = ask_magnets_histogram_config()
        ok = false;
        bins = getpref('ComsolAnalyzer', 'MagnetsHistogramBins', 100);
        stepPercent = getpref('ComsolAnalyzer', 'MagnetsHistogramStepPercent', 2);
        br = getpref('ComsolAnalyzer', 'MagnetsHistogramBr', 1.4);

        answer = inputdlg({'Number of bins:', 'Step percent (%):', 'Br (Tesla):'}, ...
            'Magnets Histogram', 1, {num2str(bins), num2str(stepPercent), num2str(br)});
        if isempty(answer)
            return;
        end

        binsValue = str2double(strtrim(answer{1}));
        stepValue = str2double(strtrim(answer{2}));
        brValue = str2double(strtrim(answer{3}));

        if isnan(binsValue) || ~isfinite(binsValue) || binsValue < 1 || floor(binsValue) ~= binsValue
            uialert(fig, 'El valor de bins debe ser un entero positivo.', 'Valor inválido');
            return;
        end
        if isnan(stepValue) || ~isfinite(stepValue) || stepValue <= 0
            uialert(fig, 'El valor de step_percent debe ser mayor a 0.', 'Valor inválido');
            return;
        end
        if isnan(brValue) || ~isfinite(brValue) || brValue <= 0
            uialert(fig, 'El valor de Br debe ser mayor a 0.', 'Valor inválido');
            return;
        end

        bins = floor(binsValue);
        stepPercent = stepValue;
        br = brValue;
        setpref('ComsolAnalyzer', 'MagnetsHistogramBins', bins);
        setpref('ComsolAnalyzer', 'MagnetsHistogramStepPercent', stepPercent);
        setpref('ComsolAnalyzer', 'MagnetsHistogramBr', br);
        ok = true;
    end

    function shouldProceed = preview_custom_coordinate_configuration(coordCfg, coords, previewText)
        shouldProceed = false;
        previewFig = [];

        try
            previewFig = uifigure('Name', 'Custom Coordinates Preview', ...
                'Position', [220 120 820 680], ...
                'WindowStyle', 'modal', ...
                'Resize', 'on');
            previewFig.Tag = 'ComsolAnalyzerChildDialog';
            registerChildDialog(previewFig);

            uilabel(previewFig, ...
                'Text', previewText, ...
                'Position', [20 640 760 22], ...
                'FontWeight', 'bold');

            ax = uiaxes(previewFig, 'Position', [20 90 780 510]);
            scatter3(ax, coords(:, 1), coords(:, 2), coords(:, 3), 40, coords(:, 3), 'filled');
            grid(ax, 'on');
            axis(ax, 'equal');
            view(ax, 3);
            xlabel(ax, 'X [m]');
            ylabel(ax, 'Y [m]');
            zlabel(ax, 'Z [m]');
            title(ax, 'Preview de puntos seleccionados');
            colormap(ax, inferno_colormap(256));

            btnYes = uibutton(previewFig, 'push', ...
                'Text', 'Yes, use these points', ...
                'Position', [520 24 140 34], ...
                'ButtonPushedFcn', @on_preview_yes, ...
                'FontWeight', 'bold');
            btnNo = uibutton(previewFig, 'push', ...
                'Text', 'No, edit values', ...
                'Position', [670 24 130 34], ...
                'ButtonPushedFcn', @on_preview_no);
            btnYes.Enable = 'on';
            btnNo.Enable = 'on';

            previewFig.CloseRequestFcn = @on_preview_no;
            uiwait(previewFig);
        catch err
            if ~isempty(previewFig) && isvalid(previewFig)
                unregisterChildDialog(previewFig);
                delete(previewFig);
            end
            uialert(fig, ['No se pudo generar la previsualizacion de coordenadas: ' err.message], ...
                'Preview error');
            return;
        end

        function on_preview_yes(~, ~)
            shouldProceed = true;
            close_preview_figure();
        end

        function on_preview_no(~, ~)
            shouldProceed = false;
            close_preview_figure();
        end

        function close_preview_figure()
            if ~isempty(previewFig) && isvalid(previewFig)
                try
                    uiresume(previewFig);
                catch
                end
                unregisterChildDialog(previewFig);
                delete(previewFig);
            end
        end
    end

    function coords = build_spherical_coordinate_matrix(nTheta, nPhi, rMeters)
        theta = linspace(0, 2*pi, nTheta);
        phi = linspace(0, pi, nPhi);
        [thetaGrid, phiGrid] = meshgrid(theta, phi);

        xCoords = rMeters .* sin(phiGrid) .* cos(thetaGrid);
        yCoords = rMeters .* sin(phiGrid) .* sin(thetaGrid);
        zCoords = rMeters .* cos(phiGrid);
        coords = [xCoords(:), yCoords(:), zCoords(:)];
    end

    function previewFilePath = write_coordinate_preview_file(coordCfg, coords)
        fileName = sprintf('Coordinates_Spherical_coord_ntheta_%d_nphi_%d_R%smm.txt', ...
            coordCfg.nTheta, coordCfg.nPhi, format_mm_token(coordCfg.R * 1000));
        previewFilePath = fullfile(tempdir, fileName);
        writematrix(coords, previewFilePath, 'Delimiter', 'tab');
    end

    function token = format_mm_token(rMm)
        if abs(rMm - round(rMm)) < 1e-9
            token = sprintf('%d', round(rMm));
            return;
        end

        token = sprintf('%.6f', rMm);
        token = regexprep(token, '0+$', '');
        token = regexprep(token, '\.$', '');
        token = strrep(token, '.', 'p');
    end

    function tf = isFigureClosing()
        tf = ~isvalid(fig);
        if tf
            return;
        end

        s = fig.UserData;
        tf = isfield(s, 'isClosing') && logical(s.isClosing);
    end

    function registerChildDialog(dlg)
        if isFigureClosing() || ~isvalid(dlg)
            return;
        end

        s = fig.UserData;
        validDialogs = getValidChildDialogs(s.childDialogs);
        s.childDialogs = [validDialogs; {dlg}]; %#ok<AGROW>
        fig.UserData = s;
    end

    function unregisterChildDialog(dlg)
        if ~isvalid(fig)
            return;
        end

        s = fig.UserData;
        if isempty(s.childDialogs)
            return;
        end

        remaining = getValidChildDialogs(s.childDialogs);
        remaining = remaining(~cellfun(@(item) item == dlg, remaining));
        s.childDialogs = remaining;
        fig.UserData = s;
    end

    function validDialogs = getValidChildDialogs(dialogList)
        if isempty(dialogList)
            validDialogs = {};
            return;
        end

        validDialogs = dialogList(cellfun(@(item) isvalid(item), dialogList));
    end

    function closeMainFigure(src, ~)
        if ~isvalid(src)
            return;
        end

        s = src.UserData;
        if isfield(s, 'isClosing') && logical(s.isClosing)
            return;
        end

        s.isClosing = true;
        s.model = [];
        s.datasets = [];
        src.UserData = s;

        stopExtractionHeartbeat([]);

        if isfield(s, 'childDialogs') && ~isempty(s.childDialogs)
            validDialogs = getValidChildDialogs(s.childDialogs);
            for idx = 1:numel(validDialogs)
                dlg = validDialogs{idx};
                try
                    uiresume(dlg);
                catch
                end
                try
                    delete(dlg);
                catch
                end
            end
        end

        delete(src);
    end

refreshConnectionStatus('status', false);
layoutControls();
updateRunButtonState();

end
