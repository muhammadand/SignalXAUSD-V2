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
    let currentTradePage = 1;
    let totalTradeCount = -1;
    let chartPrice = null, candleSeries = null, tpLine = null, slLine = null;
    let chartRsi = null, rsiSeries = null;
    let chartAdx = null, adxSeries = null;
    let syncing = false;   // prevent scroll-sync recursion

    let ema9Series = null, ema21Series = null, vwapSeries = null;
    let supportLines = [], resistanceLines = [];

    /* ── DOM refs ── */
    const $ = id => document.getElementById(id);
    const localClock = $('local-clock');
    const utcClock = $('utc-clock');
    const connStatus = $('conn-status');
    const trendBadge = $('trend-badge');
    const watchlistEl = $('watchlist-container');
    const historyBody = $('history-body');
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

        ema9Series = chartPrice.addSeries(LightweightCharts.LineSeries, {
            color: '#fbbf24',
            lineWidth: 1.5,
            priceLineVisible: false,
            title: 'EMA 9'
        });
        ema21Series = chartPrice.addSeries(LightweightCharts.LineSeries, {
            color: '#f43f5e',
            lineWidth: 1.5,
            priceLineVisible: false,
            title: 'EMA 21'
        });
        vwapSeries = chartPrice.addSeries(LightweightCharts.LineSeries, {
            color: '#06b6d4',
            lineWidth: 1.5,
            priceLineVisible: false,
            title: 'VWAP'
        });

        /* ── ResizeObserver (responsive) ── */
        const ro = new ResizeObserver(() => {
            if (chartPrice && priceEl.clientWidth > 0) chartPrice.resize(priceEl.clientWidth, priceEl.clientHeight || chartPrice.options().height);
        });
        ro.observe(priceEl);
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
        const ema9Data = data[`ema9_${tf}`] || [];
        const ema21Data = data[`ema21_${tf}`] || [];
        const vwapData = data[`vwap_${tf}`] || [];

        // AMD state
        const amd = data.amd_info || {};

        const chartCandles = toChartCandles(candles);
        const ema9Line = toLineData(ema9Data);
        const ema21Line = toLineData(ema21Data);
        const vwapLine = toLineData(vwapData);

        if (candleSeries && chartCandles.length) {
            try { candleSeries.setData(chartCandles); } catch (e) { }
        }
        if (ema9Series && ema9Line.length) {
            try { ema9Series.setData(ema9Line); } catch (e) { }
        }
        if (ema21Series && ema21Line.length) {
            try { ema21Series.setData(ema21Line); } catch (e) { }
        }
        if (vwapSeries && vwapLine.length) {
            try { vwapSeries.setData(vwapLine); } catch (e) { }
        }

        // Draw AMD Accumulation Box lines
        if (candleSeries) {
            supportLines.forEach(line => { try { candleSeries.removePriceLine(line); } catch (e) { } });
            supportLines = [];
            resistanceLines.forEach(line => { try { candleSeries.removePriceLine(line); } catch (e) { } });
            resistanceLines = [];

            if (amd.box_high && amd.box_low) {
                const resLine = candleSeries.createPriceLine({
                    price: parseFloat(amd.box_high),
                    color: '#f43f5e',
                    lineWidth: 1,
                    lineStyle: 2,
                    axisLabelVisible: true,
                    title: 'AMD RES'
                });
                resistanceLines.push(resLine);

                const supLine = candleSeries.createPriceLine({
                    price: parseFloat(amd.box_low),
                    color: '#10b981',
                    lineWidth: 1,
                    lineStyle: 2,
                    axisLabelVisible: true,
                    title: 'AMD SUP'
                });
                supportLines.push(supLine);
            }
        }

        // AMD Manipulation Markers
        if (candleSeries && amd.manipulation_epoch) {
            const markers = [];
            const isBuy = data.signal && data.signal.type === 'BUY';
            // Determine direction based on price vs box if signal is not set yet
            let manipulationIsDown = isBuy;
            if (!data.signal || data.signal.type === 'NONE') {
                if (amd.vwap_target && amd.vwap_target < amd.box_high) {
                    manipulationIsDown = true;
                }
            }
            markers.push({
                time: amd.manipulation_epoch,
                position: manipulationIsDown ? 'belowBar' : 'aboveBar',
                color: manipulationIsDown ? '#f43f5e' : '#10b981',
                shape: manipulationIsDown ? 'arrowUp' : 'arrowDown',
                text: 'Manipulation',
            });
            try { candleSeries.setMarkers(markers); } catch (e) { }
        } else if (candleSeries) {
            try { candleSeries.setMarkers([]); } catch (e) { }
        }

        // Update indicators metrics panel
        updateMetricsBar(data);

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

    /* ─── DOM UPDATES ─── */
    function updateMetricsBar(data) {
        const tf = activeTF.toLowerCase();

        // ATR
        const atrVal = data[`atr_${tf}`];
        const atrEl = $('val-atr');
        if (atrEl) atrEl.textContent = atrVal !== undefined && atrVal !== null ? parseFloat(atrVal).toFixed(2) : '—';

        // VWAP
        const vwapData = data[`vwap_${tf}`] || [];
        const vwapEl = $('val-vwap');
        if (vwapEl) {
            const lastVwap = vwapData.length ? vwapData[vwapData.length - 1].value : null;
            vwapEl.textContent = lastVwap !== null ? lastVwap.toFixed(2) : '—';
        }

        // EMA9
        const ema9Data = data[`ema9_${tf}`] || [];
        const ema9El = $('val-ema9');
        if (ema9El) {
            const lastEma9 = ema9Data.length ? ema9Data[ema9Data.length - 1].value : null;
            ema9El.textContent = lastEma9 !== null ? lastEma9.toFixed(2) : '—';
        }

        // EMA21
        const ema21Data = data[`ema21_${tf}`] || [];
        const ema21El = $('val-ema21');
        if (ema21El) {
            const lastEma21 = ema21Data.length ? ema21Data[ema21Data.length - 1].value : null;
            ema21El.textContent = lastEma21 !== null ? lastEma21.toFixed(2) : '—';
        }

        // RR Ratio
        const rrVal = data.rr_ratio;
        const rrEl = $('val-rr');
        if (rrEl) rrEl.textContent = rrVal !== undefined && rrVal !== null ? `1:${parseFloat(rrVal).toFixed(1)}` : '—';
    }

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
            const sigRrEl = $('signal-rr');
            if (sigRrEl) sigRrEl.textContent = `1:${parseFloat(data.rr_ratio).toFixed(1)}`;
            confVal.textContent = `${sig.confidence}%`;
            confBar.style.width = `${sig.confidence}%`;
            confBar.className = `h-full rounded-full transition-all duration-500 ${isBuy
                ? 'bg-gradient-to-r from-emerald-500 to-teal-400 shadow-[0_0_8px_#10b981]'
                : 'bg-gradient-to-r from-rose-500 to-pink-400 shadow-[0_0_8px_#f43f5e]'}`;
        } else {
            signalBadge.textContent = 'SCANNING';
            signalBadge.className = 'px-3 py-0.5 text-[11px] font-black font-mono rounded border border-amber-500/40 text-amber-400 bg-amber-500/10';
            signalEntry.textContent = signalSl.textContent = signalTp.textContent = '—';
            const sigRrEl = $('signal-rr');
            if (sigRrEl) sigRrEl.textContent = '—';
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
        const posRrEl = $('pos-rr');
        if (posRrEl) posRrEl.textContent = p.active ? `1:${parseFloat(data.rr_ratio).toFixed(1)}` : '—';
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

    function renderTradeHistory(trades) {
        if (!trades || !trades.length) {
            historyBody.innerHTML = `<tr><td colspan="10" class="py-4 text-center text-gray-600 italic">No trades yet...</td></tr>`;
            return;
        }
        historyBody.innerHTML = '';
        trades.forEach(t => {
            const isWin = t.result === 'WIN';
            const pnlColor = parseFloat(t.pnl) >= 0 ? 'text-emerald-400' : 'text-rose-500';
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-white/[0.015] transition-colors border-b border-white/[0.02]';
            tr.innerHTML = `
                <td class="py-2 text-gray-400">${t.time}</td>
                <td class="py-2 font-bold ${t.type === 'BUY' ? 'text-emerald-400' : 'text-rose-500'}">${t.type}</td>
                <td class="py-2 text-gray-300 text-left">${t.pattern || 'EMA+RSI Scalper'}</td>
                <td class="py-2 text-gray-300 text-left">${t.candle_pattern || 'None'}</td>
                <td class="py-2 text-center text-amber-400 font-bold">${t.confidence ? t.confidence + '%' : '—'}</td>
                <td class="py-2 text-right text-gray-300">${t.entry}</td>
                <td class="py-2 text-right text-gray-300">${t.exit}</td>
                <td class="py-2 text-right font-bold ${pnlColor}">${t.pnl}</td>
                <td class="py-2 text-center">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-black uppercase ${isWin
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-500 border border-rose-500/30'}">${t.result}</span>
                </td>
                <td class="py-2 text-left pl-4 text-gray-400 text-[10px] max-w-[220px] truncate" title="${t.reason || ''}">${t.reason || 'N/A'}</td>`;
            historyBody.appendChild(tr);
        });
    }

    async function fetchTrades(page = 1) {
        try {
            const res = await fetch(`/api/trades?page=${page}&limit=10&t=${Date.now()}`);
            if (!res.ok) throw new Error('API error');
            const data = await res.json();

            currentTradePage = data.page;
            totalTradeCount = data.total_trades;

            renderTradeHistory(data.trades);

            const pagStart = $('pag-start');
            const pagEnd = $('pag-end');
            const pagTotal = $('pag-total');
            const pagCurrent = $('pag-current');
            const pagTotalPages = $('pag-total-pages');
            const btnPrev = $('btn-prev');
            const btnNext = $('btn-next');

            if (pagStart && pagEnd && pagTotal && pagCurrent && pagTotalPages && btnPrev && btnNext) {
                const total = data.total_trades;
                const limit = data.limit;
                const start = total === 0 ? 0 : (data.page - 1) * limit + 1;
                const end = Math.min(data.page * limit, total);

                pagStart.textContent = start;
                pagEnd.textContent = end;
                pagTotal.textContent = total;
                pagCurrent.textContent = data.page;
                pagTotalPages.textContent = data.total_pages;

                btnPrev.disabled = (data.page <= 1);
                btnNext.disabled = (data.page >= data.total_pages);
            }
        } catch (err) {
            console.error('Failed to fetch trades:', err);
        }
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
            const res = await fetch(`/api/state?t=${Date.now()}`);
            if (!res.ok) throw new Error('API error');
            const data = await res.json();
            allData = data;

            connStatus.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_6px_#10b981] live-dot"></span> ONLINE';
            connStatus.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 bg-emerald-500/10 border border-emerald-500/30 rounded-full text-emerald-400';

            updateCharts(data);
            updateSignalPanel(data);
            updatePortfolio(data);
            updateStats(data);
            // If total trades count changed on server, refresh the active page
            const serverTotalTrades = data.stats ? data.stats.total_trades : 0;
            if (serverTotalTrades !== totalTradeCount) {
                fetchTrades(currentTradePage);
            }
            updateWatchlist(data);
            updateTrendBadge(data);

        } catch (err) {
            connStatus.innerHTML = '<span class="w-2 h-2 rounded-full bg-rose-500"></span> DISCONNECTED';
            connStatus.className = 'flex items-center gap-1.5 font-mono text-[11px] px-3 py-1 bg-rose-500/10 border border-rose-500/30 rounded-full text-rose-400';
        }
    }

    /* ── Boot ── */
    try { initCharts(); } catch (e) { console.error('Chart init failed:', e); }

    // Pagination event listeners
    const btnPrev = $('btn-prev');
    const btnNext = $('btn-next');
    if (btnPrev) {
        btnPrev.addEventListener('click', () => {
            if (currentTradePage > 1) {
                fetchTrades(currentTradePage - 1);
            }
        });
    }
    if (btnNext) {
        btnNext.addEventListener('click', () => {
            fetchTrades(currentTradePage + 1);
        });
    }

    fetchTrades(1);
    fetchState();
    setInterval(fetchState, 500);

    /* ════════════════════════════════════════════════
       ECONOMIC CALENDAR
    ════════════════════════════════════════════════ */
    async function fetchEconomicCalendar() {
        const calBody = $('calendar-body');
        if (!calBody) return;

        try {
            // Get current date
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');

            // Format timezone offset (e.g., +07:00)
            const tzo = -now.getTimezoneOffset();
            const dif = tzo >= 0 ? '+' : '-';
            const pad = (num) => String(Math.floor(Math.abs(num))).padStart(2, '0');
            const tzString = dif + pad(tzo / 60) + ':' + pad(tzo % 60);

            const startDate = `${year}-${month}-${day}T00:00:00.000${tzString}`;
            const endDate = `${year}-${month}-${day}T23:59:59.999${tzString}`;

            // Note: The endpoint provided by the user
            const url = `https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences?domain_id=54&limit=200&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&country_ids=25,6,37,72,39,14,48,35,42,43,44,45,36,11,41,46,4,5,22,17,10,26,12,178`;

            const res = await fetch(url, {
                headers: {
                    'Accept': 'application/json'
                }
            });
            if (!res.ok) throw new Error('API fetch failed with status ' + res.status);
            const result = await res.json();

            // Build event metadata lookup if 'events' array exists
            const eventMeta = {};
            if (result.events && Array.isArray(result.events)) {
                result.events.forEach(e => {
                    if (e.event_id) eventMeta[e.event_id] = e;
                });
            }

            // The actual schedule is usually in 'data', fallback to 'events' if 'data' is missing
            const occurrences = result.data || (Array.isArray(result) ? result : (result.events || []));

            calBody.innerHTML = '';

            if (!occurrences || !occurrences.length) {
                calBody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-gray-600 italic">No economic events today</td></tr>';
                return;
            }

            // Try to sort by time if possible
            occurrences.sort((a, b) => {
                const dateA = new Date(a.datetime || a.timestamp || a.date || a.time || 0);
                const dateB = new Date(b.datetime || b.timestamp || b.date || b.time || 0);
                return dateA - dateB;
            });

            occurrences.forEach(occ => {
                const meta = (occ.event_id && eventMeta[occ.event_id]) ? eventMeta[occ.event_id] : occ;

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-white/[0.015] transition-colors';

                // Extract fields dynamically
                const rawTime = occ.datetime || occ.timestamp || occ.date || occ.time || meta.datetime || meta.time;
                let timeStr = '—';
                if (rawTime) {
                    const d = new Date(rawTime);
                    if (!isNaN(d.getTime())) {
                        timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    } else if (typeof rawTime === 'string') {
                        timeStr = rawTime.includes(' ') ? rawTime.split(' ')[1].substring(0, 5) : rawTime;
                    }
                }

                const ctry = occ.currency || meta.currency || occ.country_code || (occ.country ? occ.country.code : '—') || '—';
                const name = occ.event_translated || meta.event_translated || occ.short_name || meta.short_name || occ.name || meta.name || occ.title || meta.title || '—';

                // Keep actual/forecast/prev as strings or numbers, handle nulls
                const actual = occ.actual_formatted || (occ.actual !== null && occ.actual !== undefined ? occ.actual : '—');
                const forecast = occ.forecast_formatted || (occ.forecast !== null && occ.forecast !== undefined ? occ.forecast : '—');
                const prev = occ.previous_formatted || (occ.previous !== null && occ.previous !== undefined ? occ.previous : '—');

                // Importance (low, medium, high or 1, 2, 3)
                const impRaw = occ.importance || meta.importance || 1;
                let impLevel = 1;
                if (typeof impRaw === 'string') {
                    if (impRaw.toLowerCase() === 'high') impLevel = 3;
                    else if (impRaw.toLowerCase() === 'medium') impLevel = 2;
                    else if (impRaw.toLowerCase() === 'low') impLevel = 1;
                } else {
                    impLevel = parseInt(impRaw) || 1;
                }

                let impStars = '';
                let impColor = 'text-gray-500';
                if (impLevel >= 3) { impStars = '★★★'; impColor = 'text-rose-500 font-bold glow-red'; }
                else if (impLevel == 2) { impStars = '★★'; impColor = 'text-amber-400 glow-amber'; }
                else { impStars = '★'; impColor = 'text-gray-500'; }

                tr.innerHTML = `
                    <td class="py-2 text-gray-400">${timeStr}</td>
                    <td class="py-2 font-bold text-gray-300 uppercase">${ctry}</td>
                    <td class="py-2 text-gray-200" title="${meta.description || ''}">${name}</td>
                    <td class="py-2 text-center ${impColor}">${impStars}</td>
                    <td class="py-2 text-right font-bold text-gray-100">${actual}</td>
                    <td class="py-2 text-right text-gray-400">${forecast}</td>
                    <td class="py-2 text-right text-gray-500">${prev}</td>
                `;
                calBody.appendChild(tr);
            });

        } catch (err) {
            calBody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-rose-500 italic">Failed to load calendar data (CORS or Error)</td></tr>`;
            console.error('Economic calendar fetch error:', err);
        }
    }

    fetchEconomicCalendar();
    setInterval(fetchEconomicCalendar, 5 * 60 * 1000); // refresh every 5m

});
