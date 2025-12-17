window.dash_clientside = Object.assign({}, window.dash_clientside, {
    settings: {
        updateAccordionStore: function(active_item) {
            if (active_item === undefined) {
                return window.dash_clientside.no_update;
            }
            return active_item;
        }
    }
});
