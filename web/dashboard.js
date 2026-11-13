const { createApp, ref, computed, onMounted } = Vue;
const { createChart, CandlestickSeries, HistogramSeries } = LightweightCharts;

createApp({
  setup() {
    const chartElement = ref(null);
    const connected = ref(false);
    const status = ref({});
    const recorded = ref(null);
    const current = ref(null);
    const replaying = ref(false);
    const notice = ref("");
    const now = ref(Date.now());
    const liveRows = new Map();
    const replayRows = new Map();
    let chart, candles, volume, socket;
    let replayRun = 0;

    const feedState = computed(() => replaying.value ? "replay" :
      connected.value ? status.value.state || "connecting" : "local connection lost");
    const source = computed(() => replaying.value ? recorded.value?.source_ms : status.value.source_ms);
    const sourceTime = computed(() => source.value ?
      new Date(source.value).toISOString().slice(11, 23) : "—");
    const age = computed(() => {
      if (!source.value) return "—";
      const end = replaying.value ? recorded.value.receipt_ms : now.value;
      return Math.max(0, (end - source.value) / 1000).toFixed(1) + " s";
    });
    const observationLabel = computed(() => {
      const id = replaying.value ? recorded.value?.id : status.value.observation_id;
      return id ? "#" + id : "—";
    });
    const candleState = computed(() => current.value ?
      current.value.complete ? "Last candle complete" : "Current candle open" : "");

    function render(fit = false) {
      const rows = [...(replaying.value ? replayRows : liveRows).values()]
        .sort((a, b) => a.start_ms - b.start_ms).slice(-60);
      current.value = rows.at(-1);
      candles.setData(rows.map(row => ({
        time: row.start_ms / 1000, open: row.open, high: row.high, low: row.low, close: row.close,
      })));
      volume.setData(rows.map(row => {
        const time = row.start_ms / 1000;
        if (row.volume === null) return { time };
        return { time, value: row.volume, color: row.close >= row.open ? "#328974" : "#aa525f" };
      }));
      if (fit) chart.timeScale().fitContent();
    }

    function connect() {
      socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
      socket.onopen = () => { connected.value = true; };
      socket.onclose = () => {
        connected.value = false;
        if (!replaying.value) notice.value = "Reconnecting to the local backend…";
        setTimeout(connect, 1500);
      };
      socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "status") {
          status.value = message;
          if (!replaying.value) {
            notice.value = message.simulated ? "Simulated outage. The last chart remains visible." :
              message.state === "unavailable" ? "Yahoo quote connection unavailable. Retrying…" :
              message.state === "stale" ? "Latest Yahoo quote is more than 90 seconds old." : "";
          }
          return;
        }
        const firstBar = liveRows.size === 0;
        if (message.type === "snapshot") {
          liveRows.clear();
          for (const row of message.observations) liveRows.set(row.start_ms, row);
          status.value = message.status;
        } else {
          const row = message.observation;
          if (liveRows.size >= 60 && !liveRows.has(row.start_ms)) {
            const oldest = Math.min(...liveRows.keys());
            if (row.start_ms < oldest) return;
            liveRows.delete(oldest);
          }
          liveRows.set(row.start_ms, row);
        }
        if (!replaying.value) render(message.type === "snapshot" || firstBar);
      };
    }

    async function toggleReplay() {
      const run = ++replayRun;
      replaying.value = !replaying.value;
      if (!replaying.value) {
        notice.value = "";
        render(true);
        return;
      }
      replayRows.clear();
      recorded.value = null;
      render();
      notice.value = "Loading SQLite observations…";
      try {
        const response = await fetch("/api/replay");
        if (!response.ok) throw new Error("Replay request failed");
        const rows = await response.json();
        if (run !== replayRun) return;
        notice.value = rows.length ? "Playing stored observations in receipt order at a fixed pace." :
          "No stored observations yet.";
        for (const row of rows) {
          if (run !== replayRun) return;
          recorded.value = row;
          replayRows.set(row.start_ms, row);
          render(true);
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (run === replayRun && rows.length) notice.value = "Replay finished (" + rows.length + " observations).";
      } catch {
        if (run === replayRun) notice.value = "SQLite replay is unavailable.";
      }
    }

    function toggleOutage() {
      if (socket?.readyState === WebSocket.OPEN) socket.send("toggle-outage");
    }

    onMounted(() => {
      chart = createChart(chartElement.value, {
        autoSize: true,
        layout: { background: { color: "#161e29" }, textColor: "#a3b1c4", attributionLogo: true },
        grid: { vertLines: { color: "#253140" }, horzLines: { color: "#253140" } },
        timeScale: { timeVisible: true, secondsVisible: false },
      });
      candles = chart.addSeries(CandlestickSeries, {
        upColor: "#61d6ae", downColor: "#f17885", borderVisible: false,
        wickUpColor: "#61d6ae", wickDownColor: "#f17885",
      });
      candles.priceScale().applyOptions({ scaleMargins: { top: .1, bottom: .25 } });
      volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false, priceLineVisible: false,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: .78, bottom: 0 } });
      setInterval(() => { now.value = Date.now(); }, 250);
      connect();
    });

    return { chartElement, connected, status, replaying, notice, feedState, sourceTime,
      age, observationLabel, candleState, toggleReplay, toggleOutage };
  },
}).mount("#app");
