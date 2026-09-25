// Auswahlfenster mit Suche für Firma und Ort (Neuer Schein, Bearbeiten).
// Tippen filtert die Liste, ein Tipp auf einen Eintrag übernimmt ihn.
// Gibt es den Namen noch nicht, kann man ihn als neuen Eintrag übernehmen;
// angelegt wird er vom Server beim Speichern des Formulars.
(function () {
    var modalEl = document.getElementById('pickerModal');
    if (!modalEl) return;

    var titleEl = document.getElementById('pickerTitle');
    var search = document.getElementById('pickerSearch');
    var list = document.getElementById('pickerList');
    var MAX_ROWS = 200;
    var current = null;

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function norm(value) {
        return String(value || '').toLocaleLowerCase('de');
    }

    function highlight(name, query) {
        if (!query) return escapeHtml(name);
        var pos = norm(name).indexOf(query);
        if (pos < 0) return escapeHtml(name);
        return escapeHtml(name.slice(0, pos)) +
            '<mark>' + escapeHtml(name.slice(pos, pos + query.length)) + '</mark>' +
            escapeHtml(name.slice(pos + query.length));
    }

    function setValue(cfg, value) {
        cfg.hidden.value = value;
        cfg.button.textContent = value || cfg.placeholder;
        cfg.button.classList.toggle('picker-empty', !value);
    }

    function row(value, html, extraClass) {
        return '<button type="button" class="list-group-item list-group-item-action picker-row ' +
            (extraClass || '') + '" data-value="' + escapeHtml(value) + '">' + html + '</button>';
    }

    function render() {
        var raw = search.value.trim();
        var query = norm(raw);
        var matches = current.options.filter(function (name) {
            return !query || norm(name).indexOf(query) >= 0;
        });
        // Treffer am Wortanfang zuerst, sonst alphabetisch wie in der Datenbank.
        if (query) {
            matches.sort(function (a, b) {
                return (norm(a).indexOf(query) === 0 ? 0 : 1) - (norm(b).indexOf(query) === 0 ? 0 : 1);
            });
        }

        var html = '';
        if (!query && current.hidden.value) {
            html += row('', '<span class="text-body-secondary">Auswahl entfernen</span>');
        }
        matches.slice(0, MAX_ROWS).forEach(function (name) {
            var selected = name === current.hidden.value;
            html += row(name, highlight(name, query) +
                (selected ? ' <i class="bi bi-check-lg float-end" aria-hidden="true"></i>' : ''),
                selected ? 'active' : '');
        });
        if (matches.length > MAX_ROWS) {
            html += '<div class="list-group-item text-body-secondary small">' +
                (matches.length - MAX_ROWS) + ' weitere, bitte genauer suchen</div>';
        }
        var exact = current.options.some(function (name) { return norm(name) === query; });
        if (raw && !exact) {
            html += row(raw, '<i class="bi bi-plus-lg me-2" aria-hidden="true"></i>' +
                '„' + escapeHtml(raw) + '“ ' + escapeHtml(current.newLabel), 'picker-new');
        }
        if (!html) {
            html = '<div class="list-group-item text-body-secondary">Noch keine Einträge. Namen oben eingeben.</div>';
        }
        list.innerHTML = html;
        list.scrollTop = 0;
    }

    function open(cfg) {
        current = cfg;
        titleEl.textContent = cfg.title;
        search.value = '';
        render();
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    document.querySelectorAll('[data-picker]').forEach(function (button) {
        var cfg = {
            button: button,
            hidden: document.getElementById(button.dataset.picker),
            title: button.dataset.title,
            placeholder: button.dataset.placeholder,
            newLabel: button.dataset.newLabel,
            options: JSON.parse(button.dataset.options || '[]')
        };
        setValue(cfg, cfg.hidden.value);
        button.addEventListener('click', function () { open(cfg); });
    });

    modalEl.addEventListener('shown.bs.modal', function () { search.focus(); });
    search.addEventListener('input', render);

    // Enter übernimmt den ersten Eintrag (bzw. "neu anlegen", wenn nichts passt).
    // stopPropagation, damit der globale Enter-Handler in base.html nicht greift.
    search.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        e.stopPropagation();
        var rows = list.querySelectorAll('[data-value]');
        var first = null;
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].dataset.value) { first = rows[i]; break; }
        }
        if (first) first.click();
    });

    list.addEventListener('click', function (e) {
        var target = e.target.closest('[data-value]');
        if (!target || !current) return;
        setValue(current, target.dataset.value);
        bootstrap.Modal.getInstance(modalEl).hide();
    });
})();
