function reset_all_hidden_nodes(model)
    fprintf('[DBG] Reset hidden nodes/entities in model views and geometries...\n');

    compTags = {};
    try
        compTags = cell(model.component.tags);
    catch
        compTags = {'comp1'};
    end

    for ic = 1:numel(compTags)
        compTag = compTags{ic};

        viewTags = {};
        try
            viewTags = cell(model.component(compTag).view.tags);
        catch
            viewTags = {};
        end

        for iv = 1:numel(viewTags)
            viewTag = viewTags{iv};

            propCandidates = {
                'showhiddenentities', 'on';
                'showhiddenobjects',  'on';
                'showhidden',         'on';
                'showhiddengeom',     'on';
                'showhiddengeomobj',  'on';
                'showgeomobjects',    'on';
                'showobjects',        'on';
                'showmaterialdomains','on';
                'showselection',      'on'
            };

            for ip = 1:size(propCandidates,1)
                try
                    model.component(compTag).view(viewTag).set(propCandidates{ip,1}, propCandidates{ip,2});
                catch
                end
                try
                    model.component(compTag).view(viewTag).set(propCandidates{ip,1}, true);
                catch
                end
                try
                    model.component(compTag).view(viewTag).set(propCandidates{ip,1}, 1);
                catch
                end
            end

            viewFeatTags = {};
            try
                viewFeatTags = cell(model.component(compTag).view(viewTag).feature.tags);
            catch
                viewFeatTags = {};
            end

            for ift = 1:numel(viewFeatTags)
                ftag = viewFeatTags{ift};
                flabel = '';
                iftype = '';
                try
                    flabel = lower(char(model.component(compTag).view(viewTag).feature(ftag).label));
                catch
                end
                try
                    iftype = lower(char(model.component(compTag).view(viewTag).feature(ftag).getType));
                catch
                end

                if contains(lower(ftag), 'hide') || contains(flabel, 'hide') || contains(iftype, 'hide')
                    try
                        model.component(compTag).view(viewTag).feature(ftag).active(false);
                    catch
                    end
                    try
                        model.component(compTag).view(viewTag).feature(ftag).set('active', false);
                    catch
                    end
                    try
                        model.component(compTag).view(viewTag).feature(ftag).set('show', 'on');
                    catch
                    end
                end
            end
        end

        geomTags = {};
        try
            geomTags = cell(model.component(compTag).geom.tags);
        catch
            geomTags = {};
        end

        for ig = 1:numel(geomTags)
            geomTag = geomTags{ig};
            geomFeatTags = {};
            try
                geomFeatTags = cell(model.component(compTag).geom(geomTag).feature.tags);
            catch
                geomFeatTags = {};
            end

            for ifg = 1:numel(geomFeatTags)
                gftag = geomFeatTags{ifg};
                gflabel = '';
                gftype = '';
                try
                    gflabel = lower(char(model.component(compTag).geom(geomTag).feature(gftag).label));
                catch
                end
                try
                    gftype = lower(char(model.component(compTag).geom(geomTag).feature(gftag).getType));
                catch
                end

                if contains(lower(gftag), 'hide') || contains(gflabel, 'hide') || contains(gftype, 'hide')
                    try
                        model.component(compTag).geom(geomTag).feature(gftag).active(false);
                    catch
                    end
                    try
                        model.component(compTag).geom(geomTag).feature(gftag).set('active', false);
                    catch
                    end
                end
            end

            try
                model.component(compTag).geom(geomTag).run;
            catch
            end
        end
    end

    fprintf('[DBG] Hidden reset complete.\n');
end
