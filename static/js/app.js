/* ================================================================
   TCINVEST PRO STATION — Frontend Controller
   - Triple synchronized charts: Price / RSI / ADX
   - TP (blue) + SL (red) horizontal price lines on main chart
   - Lines disappear when trade closes, new analysis shown
   - M1 / M5 / H1 / H4 timeframe switching
   - Win rate scoreboard + trade history
   ================================================================ */

document.addEventListener('DOMContentLoaded', () => {

    /* ── Guard: must open via http://127.0.0.1:5000 ── */
    if (window.location.protocol === 'file:') {
        alert('Open http://127.0.0.1:5000 in your browser (run python3 main.py first).');
        return;
    }

    /* ── State ── */
    let activeTF = 'M1';
    let allData = {};
    let chartPrice = null, candleSeries = null, tpLine = null, slLine = null;
    let chartRsi = null, rsiSeries = null;
    let chartAdx = null, adxSeries = null;
    let syncing = false;   // prevent scroll-sync recursion

    /* ── DOM refs ── */
    const $ = id => document.getElementById(id);
    const localClock = $('local-clock');
    const utcClock = $('utc-clock');
    const connStatus = $('conn-status');
    const trendBadge = $('trend-badge');
    const watchlistEl = $('watchlist-container');
    const historyBody = $('history-body');
    const calendarBody = $('calendar-body');
    const signalBadge = $('signal-badge');
    const signalEntry = $('signal-entry');
    const signalSl = $('signal-sl');
    const signalTp = $('signal-tp');
    const signalReason = $('signal-reason');
    const confVal = $('signal-conf-val');
    const confBar = $('signal-conf-bar');
    const posEntry = $('pos-entry');
    const posMarket = $('pos-market');
    const posPnl = $('pos-pnl');
    const posStatus = $('pos-status');
    const statWins = $('stat-wins');
    const statLosses = $('stat-losses');
    const statWinrate = $('stat-winrate');
    const statTotal = $('stat-total');
    const wrBar = $('wr-bar');

    /* ── Live clocks ── */
    function updateClocks() {
        const now = new Date();
        localClock.textContent = now.toLocaleTimeString();
        utcClock.textContent = now.toISOString().slice(11, 19) + ' UTC';
    }
    setInterval(updateClocks, 1000);
    updateClocks();

    /* ════════════════════════════════════════════════
       CHART INITIALISATION
    ════════════════════════════════════════════════ */
    const DARK_BG = '#05080b';
    const GRID = 'rgba(255,255,255,0.025)';

    function baseChartOpts(height) {
        return {
            width: 0,   // will be resized by observer
            height: height,
            layout: { background: { type: 'solid', color: DARK_BG }, textColor: '#6b7280', fontSize: 10, fontFamily: "'Source Code Pro', monospace" },
            grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            timeScale: { borderColor: 'rgba(255,255,255,0.04)', timeVisible: true, secondsVisible: false },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.04)' },
            handleScroll: true,
            handleScale: true,
        };
    }

    function initCharts() {
        /* ── Price chart ── */
        const priceEl = $('chart-price');
        chartPrice = LightweightCharts.createChart(priceEl, baseChartOpts(280));
        chartPrice.applyOptions({
            crosshair: {
                vertLine: { color: 'rgba(245,158,11,0.5)', labelBackgroundColor: '#f59e0b' },
                horzLine: { color: 'rgba(245,158,11,0.5)', labelBackgroundColor: '#f59e0b' },
            }
        });
        candleSeries = chartPrice.addSeries(LightweightCharts.CandlestickSeries, {
            upColor: '#10b981', downColor: '#f43f5e',
            borderUpColor: '#10b981', borderDownColor: '#f43f5e',
            wickUpColor: '#10b981', wickDownColor: '#f43f5e',
        });

        /* ── RSI chart ── */
        const rsiEl = $('chart-rsi');
        chartRsi = LightweightCharts.createChart(rsiEl, baseChartOpts(90));
        chartRsi.applyOptions({ rightPriceScale: { scaleMargins: { top: 0.05, bottom: 0.05 } } });
        rsiSeries = chartRsi.addSeries(LightweightCharts.LineSeries, { color: '#a78bfa', lineWidth: 1.5, priceLineVisible: false });

        // RSI reference lines (drawn as separate line series)
        const rsiOver = chartRsi.addSeries(LightweightCharts.LineSeries, { color: 'rgba(244,63,94,0.35)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false });
        const rsiUnder = chartRsi.addSeries(LightweightCharts.LineSeries, { color: 'rgba(16,185,129,0.35)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false });
        window._rsiOver = rsiOver;
        window._rsiUnder = rsiUnder;

        /* ── ADX chart ── */
        const adxEl = $('chart-adx');
        chartAdx = LightweightCharts.createChart(adxEl, baseChartOpts(80));
        chartAdx.applyOptions({ rightPriceScale: { scaleMargins: { top: 0.05, bottom: 0.05 } } });
        adxSeries = chartAdx.addSeries(LightweightCharts.LineSeries, { color: '#38bdf8', lineWidth: 1.5, priceLineVisible: false });

        // ADX strength line at 25
        const adxRef = chartAdx.addSeries(LightweightCharts.LineSeries, { color: 'rgba(245,158,11,0.4)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false });
        window._adxRef = adxRef;

        /* ── ResizeObserver (responsive) ── */
        const ro = new ResizeObserver(() => {
            [priceEl, rsiEl, adxEl].forEach(el => {
                const chart = el === priceEl ? chartPrice : el === rsiEl ? chartRsi : chartAdx;
                if (chart && el.clientWidth > 0) chart.resize(el.clientWidth, el.clientHeight || chart.options().height);
            });
        });
        [priceEl, rsiEl, adxEl].forEach(el => ro.observe(el));

        /* ── Synchronized scroll/zoom ── */
        function syncTimeRange(source, targets) {
            source.timeScale().subscribeVisibleTimeRangeChange(() => {
                if (syncing) return;
                syncing = true;
                const range = source.timeScale().getVisibleRange();
                if (range) targets.forEach(t => t.timeScale().setVisibleRange(range));
                syncing = false;
            });
        }
        syncTimeRange(chartPrice, [chartRsi, chartAdx]);
        syncTimeRange(chartRsi, [chartPrice, chartAdx]);
        syncTimeRange(chartAdx, [chartPrice, chartRsi]);
    }

    /* ════════════════════════════════════════════════
       CHART DATA UPDATE
    ════════════════════════════════════════════════ */
    function toChartCandles(arr) {
        if (!arr || !arr.length) return [];
        const seen = new Set();
        return arr
            .map(c => ({ time: c.epoch, open: c.open, high: c.high, low: c.low, close: c.close }))
            .sort((a, b) => a.time - b.time)
            .filter(c => { if (seen.has(c.time)) return false; seen.add(c.time); return true; });
    }

    function toLineData(arr) {
        if (!arr || !arr.length) return [];
        const seen = new Set();
        return arr
            .filter(p => p.value !== null && p.value !== undefined && !isNaN(p.value))
            .sort((a, b) => a.epoch - b.epoch)
            .filter(p => { if (seen.has(p.epoch)) return false; seen.add(p.epoch); return true; })
            .map(p => ({ time: p.epoch, value: parseFloat(p.value.toFixed(2)) }));
    }

    function makeFlatLine(lineData, fixedVal) {
        return lineData.map(p => ({ time: p.time, value: fixedVal }));
    }

    let lastTpVal = null, lastSlVal = null, signalActive = false;

    function updateCharts(data) {
        const tf = activeTF.toLowerCase();
        const candles = data[`candles_${tf}`] || [];
        const rsiData = data[`rsi_${tf}`] || [];
        const adxData = data[`adx_${tf}`] || [];

        const chartCandles = toChartCandles(candles);
        const rsiLine = toLineData(rsiData);
        const adxLine = toLineData(adxData);

        if (candleSeries && chartCandles.length) {
            try { candleSeries.setData(chartCandles); } catch (e) { }
        }
        if (rsiSeries && rsiLine.length) {
            try {
                rsiSeries.setData(rsiLine);
                if (window._rsiOver) window._rsiOver.setData(makeFlatLine(rsiLine, 70));
                if (window._rsiUnder) window._rsiUnder.setData(makeFlatLine(rsiLine, 30));
            } catch (e) { }
        }
        if (adxSeries && adxLine.length) {
            try {
                adxSeries.setData(adxLine);
                if (window._adxRef) window._adxRef.setData(makeFlatLine(adxLine, 25));
            } catch (e) { }
        }

        /* ── TP / SL price lines ── */
        const sig = data.signal || {};
        const nowActive = sig.active && sig.type !== 'NONE';
        const tpVal = parseFloat(sig.tp);
        const slVal = parseFloat(sig.sl);

        if (candleSeries) {
            if (!nowActive) {
                // Trade closed → remove lines
                if (tpLine) { try { candleSeries.removePriceLine(tpLine); } catch (e) { } tpLine = null; }
                if (slLine) { try { candleSeries.removePriceLine(slLine); } catch (e) { } slLine = null; }
                lastTpVal = lastSlVal = null;
            } else if (nowActive && (tpVal !== lastTpVal || slVal !== lastSlVal)) {
                // New signal → redraw lines
                if (tpLine) { try { candleSeries.removePriceLine(tpLine); } catch (e) { } tpLine = null; }
                if (slLine) { try { candleSeries.removePriceLine(slLine); } catch (e) { } slLine = null; }

                const isBuy = sig.type === 'BUY';
                tpLine = candleSeries.createPriceLine({
                    price: tpVal, color: '#3b82f6',
                    lineWidth: 1, lineStyle: 1,   // dashed
                    axisLabelVisible: true,
                    title: `TP  ${tpVal.toFixed(2)}`,
                });
                slLine = candleSeries.createPriceLine({
                    price: slVal, color: '#ef4444',
                    lineWidth: 1, lineStyle: 1,
                    axisLabelVisible: true,
                    title: `SL  ${slVal.toFixed(2)}`,
                });
                lastTpVal = tpVal;
                lastSlVal = slVal;
            }
        }
    }

    /* ════════════════════════════════════════════════
       DOM UPDATES
    ════════════════════════════════════════════════ */
    function updateSignalPanel(data) {
        const sig = data.signal || {};
        const active = sig.active && sig.type !== 'NONE';

        signalReason.textContent = sig.reason || '—';

        if (active) {
            const isBuy = sig.type === 'BUY';
            signalBadge.textContent = sig.type;
            signalBadge.className = `px-3 py-0.5 text-[11px] font-black font-mono rounded border ${isBuy
                ? 'bg-emerald-500/15 border-emerald-500 text-emerald-400'
                : 'bg-rose-500/15 border-rose-500 text-rose-400'}`;
            signalEntry.textContent = sig.entry;
            signalSl.textContent = sig.sl;
            signalTp.textContent = sig.tp;
            confVal.textContent = `${sig.confidence}%`;
            confBar.style.width = `${sig.confidence}%`;
            confBar.className = `h-full rounded-full transition-all duration-500 ${isBuy
                ? 'bg-gradient-to-r from-emerald-500 to-teal-400 shadow-[0_0_8px_#10b981]'
                : 'bg-gradient-to-r from-rose-500 to-pink-400 shadow-[0_0_8px_#f43f5e]'}`;
        } else {
            signalBadge.textContent = 'SCANNING';
            signalBadge.className = 'px-3 py-0.5 text-[11px] font-black font-mono rounded border border-amber-500/40 text-amber-400 bg-amber-500/10';
            signalEntry.textContent = signalSl.textContent = signalTp.textContent = '—';
            confVal.textContent = '—'; confBar.style.width = '0%';
        }
    }

    function updatePortfolio(data) {
        const p = data.portfolio || {};
        posEntry.textContent = p.entry || '—';
        posMarket.textContent = p.market || '—';
        const pnlColor = p.pnl_color === 'green' ? 'text-emerald-400' : 'text-rose-500';
        posPnl.textContent = p.pnl || '—';
        posPnl.className = `text-right font-bold ${pnlColor}`;
        posStatus.textContent = p.status || '—';
        posStatus.className = `text-right font-semibold ${p.active ? 'text-emerald-400' : 'text-gray-500'}`;
    }

    function updateStats(data) {
        const s = data.stats || {};
        statWins.textContent = s.total_wins || '0';
        statLosses.textContent = s.total_losses || '0';
        statTotal.textContent = s.total_trades || '0';
        const wr = parseFloat(s.win_rate) || 0;
        statWinrate.textContent = `${wr.toFixed(1)}%`;
        statWinrate.className = `text-3xl font-black font-mono ${wr >= 50 ? 'text-emerald-400' : 'text-rose-500'}`;
        wrBar.style.width = `${Math.min(wr, 100)}%`;
    }

    function updateHistory(data) {
        const hist = data.trade_history || [];
        if (!hist.length) return;
        historyBody.innerHTML = '';
        hist.forEach(t => {
            const isWin = t.result === 'WIN';
            const pnlColor = parseFloat(t.pnl) >= 0 ? 'text-emerald-400' : 'text-rose-500';
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-white/[0.015] transition-colors';
            tr.innerHTML = `
                <td class="py-2 text-gray-400">${t.time}</td>
                <td class="py-2 font-bold ${t.type === 'BUY' ? 'text-emerald-400' : 'text-rose-500'}">${t.type}</td>
                <td class="py-2 text-right text-gray-300">${t.entry}</td>
                <td class="py-2 text-right text-gray-300">${t.exit}</td>
                <td class="py-2 text-right font-bold ${pnlColor}">${t.pnl}</td>
                <td class="py-2 text-center">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-black uppercase ${isWin
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-500 border border-rose-500/30'}">${t.result}</span>
                </td>`;
            historyBody.appendChild(tr);
        });
    }

    function updateWatchlist(data) {
        const wl = data.watchlist || [];
        watchlistEl.innerHTML = '';
        wl.forEach(item => {
            const clr = item.color === 'green' ? 'text-emerald-400' : item.color === 'red' ? 'text-rose-500' : 'text-gray-300';
            const div = document.createElement('div');
            div.className = 'grid grid-cols-3 items-center px-2.5 py-2 bg-white/[0.01] hover:bg-white/[0.04] border border-white/[0.03] rounded-lg font-mono text-[11px] transition-all duration-150 hover:translate-x-1';
            div.innerHTML = `<span class="font-bold text-gray-300">${item.symbol}</span><span class="text-center text-gray-100">${item.price}</span><span class="text-right text-[10px] font-bold ${clr}">${item.change} ${item.direction}</span>`;
            watchlistEl.appendChild(div);
        });
    }

    function updateCalendar(data) {
        const events = data.calendar || [];
        calendarBody.innerHTML = '';
        events.forEach(e => {
            const isBullish = e.forecast === 'BULLISH';
            const isCrit = e.volatility === 'CRITICAL';
            const volCls = isCrit ? 'text-rose-500 font-bold' : e.volatility === 'VERY HIGH' ? 'text-orange-400' : 'text-amber-400';
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-white/[0.015] transition-colors border-b border-white/[0.03]';
            tr.innerHTML = `
                <td class="py-2 text-gray-300">${e.name}</td>
                <td class="py-2 text-center text-gray-400">${e.time}</td>
                <td class="py-2 text-center text-cyan-400 font-semibold">${e.countdown}</td>
                <td class="py-2 text-center font-bold ${isBullish ? 'text-emerald-400' : 'text-rose-500'}">${e.forecast} ${isBullish ? '▲' : '▼'}</td>
                <td class="py-2 text-center ${volCls}">${e.volatility}</td>`;
            calendarBody.appendChild(tr);
        });
    }

    function updateTrendBadge(data) {
        const trend = data.market_trend || 'NEUTRAL';
        if (trend === 'BUY') {
            trendBadge.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 border border-emerald-500/40 rounded-full bg-emerald-500/10 text-emerald-400';
        } else if (trend === 'SELL') {
            trendBadge.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 border border-rose-500/40 rounded-full bg-rose-500/10 text-rose-400';
        } else {
            trendBadge.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 border border-white/[0.08] rounded-full text-gray-400';
        }
        trendBadge.innerHTML = `TREND: <strong>${trend}</strong>`;
    }

    /* ════════════════════════════════════════════════
       TIMEFRAME TAB SWITCHER
    ════════════════════════════════════════════════ */
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activeTF = btn.dataset.tf;
            document.querySelectorAll('.tf-btn').forEach(b => {
                if (b === btn) {
                    b.className = 'tf-btn active-tf px-2.5 py-1 text-[11px] font-bold font-mono rounded border border-amber-500 bg-amber-500/20 text-amber-400 transition-all cursor-pointer';
                } else {
                    b.className = 'tf-btn px-2.5 py-1 text-[11px] font-bold font-mono rounded border border-white/10 text-gray-400 hover:text-gray-200 transition-all cursor-pointer';
                }
            });
            if (Object.keys(allData).length) updateCharts(allData);
            if (chartPrice) chartPrice.timeScale().fitContent();
            if (chartRsi) chartRsi.timeScale().fitContent();
            if (chartAdx) chartAdx.timeScale().fitContent();
        });
    });

    // Set initial tab style
    document.querySelectorAll('.tf-btn').forEach(b => {
        if (b.dataset.tf === activeTF) {
            b.className = 'tf-btn active-tf px-2.5 py-1 text-[11px] font-bold font-mono rounded border border-amber-500 bg-amber-500/20 text-amber-400 transition-all cursor-pointer';
        } else {
            b.className = 'tf-btn px-2.5 py-1 text-[11px] font-bold font-mono rounded border border-white/10 text-gray-400 hover:text-gray-200 transition-all cursor-pointer';
        }
    });

    /* ════════════════════════════════════════════════
       POLLING LOOP
    ════════════════════════════════════════════════ */
    async function fetchState() {
        try {
            const res = await fetch('/api/state');
            if (!res.ok) throw new Error('API error');
            const data = await res.json();
            allData = data;

            connStatus.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_6px_#10b981] live-dot"></span> ONLINE';
            connStatus.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 bg-emerald-500/10 border border-emerald-500/30 rounded-full text-emerald-400';

            updateCharts(data);
            updateSignalPanel(data);
            updatePortfolio(data);
            updateStats(data);
            updateHistory(data);
            updateWatchlist(data);
            updateCalendar(data);
            updateTrendBadge(data);

        } catch (err) {
            connStatus.innerHTML = '<span class="w-2 h-2 rounded-full bg-rose-500"></span> DISCONNECTED';
            connStatus.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 bg-rose-500/10 border border-rose-500/30 rounded-full text-rose-400';
        }
    }

    /* ── Boot ── */
    try { initCharts(); } catch (e) { console.error('Chart init failed:', e); }
    fetchState();
    setInterval(fetchState, 500);
});
