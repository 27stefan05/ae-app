// Bildschirmtastatur der App. Erscheint unten, wenn man ein Eingabefeld
// antippt oder anklickt. Zahlenfelder (type=number, inputmode numeric/tel)
// bekommen einen Ziffernblock, alle anderen eine deutsche QWERTZ-Tastatur.
//
// - Nur bei echtem Antippen, nicht bei Fokus per Skript: Das Suchfeld auf
//   der Startseite hat immer den Fokus, die Tastatur soll trotzdem zu sein.
//   Felder mit data-osk-auto (z. B. Suche im Auswahlfenster) gehen auch auf,
//   wenn sie direkt nach einem Tipp den Fokus bekommen.
// - Die Tasten nehmen den Fokus nicht weg, Eingaben lösen ein normales
//   input-Event aus (Live-Suche usw. funktionieren).
// - Tippen auf einer echten Tastatur oder dem Scanner blendet sie aus.
// - Umschalttaste: einmal = nächster Buchstabe groß, zweimal schnell =
//   Feststelltaste (bleibt groß, bis man sie wieder antippt).
(function () {
    var AUTO_MS = 1000;
    var DOUBLE_TAP_MS = 400;
    var FULL_ROWS = [
        ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'ß', 'BACK'],
        ['q', 'w', 'e', 'r', 't', 'z', 'u', 'i', 'o', 'p', 'ü'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'ö', 'ä'],
        ['SHIFT', 'y', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '-'],
        ['HIDE', '&', '/', 'SPACE', '+', 'ENTER']
    ];
    var NUM_ROWS = [
        ['7', '8', '9'],
        ['4', '5', '6'],
        ['1', '2', '3'],
        ['BACK', '0', 'ENTER']
    ];
    var TEL_EXTRA = ['+', '/', '-', 'SPACE'];
    var LABELS = {
        BACK: '<i class="bi bi-backspace" aria-hidden="true"></i>',
        SHIFT: '',
        SPACE: 'Leertaste',
        ENTER: '<i class="bi bi-arrow-return-left" aria-hidden="true"></i>',
        HIDE: '<i class="bi bi-chevron-down" aria-hidden="true"></i>'
    };
    var ARIA = { BACK: 'Löschen', SHIFT: 'Großbuchstaben', SPACE: 'Leertaste', ENTER: 'Eingabe', HIDE: 'Tastatur schließen' };

    var panel = document.createElement('div');
    panel.id = 'osk';
    panel.className = 'osk';
    panel.setAttribute('aria-hidden', 'true');
    document.body.appendChild(panel);

    var target = null;
    var shift = false;
    var capsLock = false;
    var lastShiftTap = 0;
    var mode = null;
    var lastPointer = { el: null, time: 0 };

    function isEditable(el) {
        if (!el || el.disabled || el.readOnly) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName !== 'INPUT') return false;
        return ['text', 'search', 'password', 'number', 'tel', 'email', 'url', ''].indexOf(el.type) >= 0;
    }

    function layoutFor(el) {
        var im = (el.getAttribute('inputmode') || '').toLowerCase();
        if (el.type === 'tel' || im === 'tel') return 'tel';
        if (el.type === 'number' || im === 'numeric' || im === 'decimal') return 'num';
        return 'full';
    }

    function shiftLabel() {
        var icon = capsLock ? 'bi-capslock-fill' : (shift ? 'bi-shift-fill' : 'bi-shift');
        return '<i class="bi ' + icon + '" aria-hidden="true"></i>';
    }

    function keyHtml(key) {
        var special = key in LABELS;
        var label = key === 'SHIFT' ? shiftLabel() :
            (LABELS[key] || (shift ? key.toUpperCase().replace('SS', 'ß') : key));
        var cls = 'osk-key' + (special ? ' osk-' + key.toLowerCase() : '') +
            (key === 'SHIFT' && shift ? ' osk-active' : '') +
            (key === 'SHIFT' && capsLock ? ' osk-locked' : '');
        var aria = ARIA[key] ? ' aria-label="' + ARIA[key] + '"' : '';
        return '<button type="button" class="' + cls + '" data-key="' + key + '"' + aria + '>' + label + '</button>';
    }

    function render() {
        var rows = mode === 'full' ? FULL_ROWS : NUM_ROWS.slice();
        if (mode === 'tel') rows = [TEL_EXTRA].concat(rows);
        panel.classList.toggle('osk-full', mode === 'full');
        panel.classList.toggle('osk-num', mode !== 'full');
        panel.innerHTML = rows.map(function (row) {
            return '<div class="osk-row">' + row.map(keyHtml).join('') + '</div>';
        }).join('');
    }

    function show(el) {
        var newMode = layoutFor(el);
        target = el;
        if (newMode !== mode || !panel.classList.contains('osk-open')) {
            mode = newMode;
            // Leeres Textfeld: erster Buchstabe groß (Firmen, Orte).
            capsLock = false;
            shift = mode === 'full' && el.type !== 'password' && !el.value;
            render();
        }
        panel.classList.add('osk-open');
        panel.setAttribute('aria-hidden', 'false');
        document.body.style.paddingBottom = panel.offsetHeight + 'px';
        var rect = el.getBoundingClientRect();
        if (rect.bottom > window.innerHeight - panel.offsetHeight - 16) {
            el.scrollIntoView({ block: 'center' });
        }
    }

    function hide() {
        target = null;
        panel.classList.remove('osk-open');
        panel.setAttribute('aria-hidden', 'true');
        document.body.style.paddingBottom = '';
    }
    window.aeHideKeyboard = hide;

    function fireInput(el) {
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insert(el, text) {
        if (el.maxLength > 0 && el.value.length >= el.maxLength) return;
        // Zahlenfelder kennen keine Cursorposition: anhängen.
        if (el.type === 'number') {
            el.value = el.value + text;
        } else {
            el.setRangeText(text, el.selectionStart, el.selectionEnd, 'end');
        }
        fireInput(el);
    }

    function backspace(el) {
        if (el.type === 'number') {
            el.value = el.value.slice(0, -1);
        } else {
            var start = el.selectionStart, end = el.selectionEnd;
            if (start === end && start > 0) start -= 1;
            el.setRangeText('', start, end, 'end');
        }
        fireInput(el);
    }

    function enter(el) {
        if (el.tagName === 'TEXTAREA') {
            insert(el, '\n');
            return;
        }
        var ev = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true });
        var notPrevented = el.dispatchEvent(ev);
        // Formulare mit nur einem Feld (Login, Ort hinzufügen, max. Mappen)
        // abschicken wie mit einer echten Enter-Taste. Bei "Neuer Schein" o. ä.
        // nicht, sonst speichert ein Enter im Ziffernblock den halben Schein.
        if (notPrevented && el.form && el.form.requestSubmit) {
            var fields = Array.prototype.filter.call(el.form.elements, isEditable);
            if (fields.length === 1) el.form.requestSubmit();
        }
        hide();
    }

    function toggleShift() {
        var now = Date.now();
        if (capsLock) {
            // Aus, und der nächste Tipp zählt nicht als Doppeltipp.
            capsLock = false;
            shift = false;
            lastShiftTap = 0;
            return;
        }
        if (now - lastShiftTap < DOUBLE_TAP_MS) {
            capsLock = true;
            shift = true;
        } else {
            shift = !shift;
        }
        lastShiftTap = now;
    }

    function press(key) {
        if (!target) return;
        switch (key) {
            case 'BACK': backspace(target); break;
            case 'SHIFT': toggleShift(); render(); return;
            case 'SPACE': insert(target, ' '); break;
            case 'ENTER': enter(target); return;
            case 'HIDE': hide(); return;
            default:
                insert(target, shift && key !== 'ß' ? key.toUpperCase() : key);
                if (shift && !capsLock) { shift = false; render(); }
        }
    }

    // Tasten: Fokus nicht vom Eingabefeld wegnehmen.
    panel.addEventListener('pointerdown', function (e) { e.preventDefault(); });
    panel.addEventListener('mousedown', function (e) { e.preventDefault(); });
    panel.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-key]');
        if (btn) press(btn.dataset.key);
    });

    // Antippen eines Feldes öffnet, Antippen außerhalb schließt.
    document.addEventListener('pointerdown', function (e) {
        if (panel.contains(e.target)) return;
        lastPointer = { el: e.target, time: Date.now() };
        var field = e.target.closest ? e.target.closest('input, textarea') : null;
        if (isEditable(field)) {
            // Fokus kommt gleich; Feld mit Fokus (Startseite) sofort öffnen.
            if (document.activeElement === field) show(field);
        } else if (target) {
            hide();
        }
    }, true);

    document.addEventListener('focusin', function (e) {
        var el = e.target;
        if (!isEditable(el)) return;
        var recent = Date.now() - lastPointer.time < AUTO_MS;
        var tapped = lastPointer.el && (lastPointer.el === el || el.contains(lastPointer.el) ||
            (lastPointer.el.closest && lastPointer.el.closest('label') && lastPointer.el.closest('label').control === el));
        if (recent && (tapped || el.hasAttribute('data-osk-auto'))) show(el);
    });

    document.addEventListener('focusout', function (e) {
        if (e.target !== target) return;
        // Fokus springt auf ein anderes Feld: dort entscheidet focusin.
        setTimeout(function () {
            if (target && document.activeElement !== target) hide();
        }, 0);
    });

    // Echte Tastatur oder Scanner: Bildschirmtastatur weg.
    document.addEventListener('keydown', function (e) {
        if (e.isTrusted && target && e.key && e.key.length === 1) hide();
    }, true);

    // Fenster schließt: Tastatur mit weg.
    document.addEventListener('hidden.bs.modal', function () {
        if (target && !document.body.contains(target)) hide();
        if (target && target.closest('.modal') && !target.closest('.modal.show')) hide();
    });
})();
