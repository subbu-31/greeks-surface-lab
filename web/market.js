(function(){
  "use strict";
  var root = document.documentElement;
  function cssVar(name){ return getComputedStyle(root).getPropertyValue(name).trim(); }
  function theme(){
    return {
      text: cssVar("--text"), textDim: cssVar("--text-dim"), textFaint: cssVar("--text-faint"),
      grid: cssVar("--border"), bg: cssVar("--surface"),
      ce: cssVar("--ce"), pe: cssVar("--pe"), accent: cssVar("--accent"),
      delta: cssVar("--delta"), gamma: cssVar("--gamma"), vega: cssVar("--vega"), theta: cssVar("--theta"),
      good: cssVar("--good"), bad: cssVar("--bad")
    };
  }
  function baseLayout(extra){
    var t = theme();
    var layout = {
      paper_bgcolor: t.bg, plot_bgcolor: t.bg,
      font: { family: "IBM Plex Mono, monospace", color: t.text, size: 11 },
      margin: { l: 48, r: 16, t: 8, b: 40 },
      xaxis: { gridcolor: t.grid, zerolinecolor: t.grid, color: t.text },
      yaxis: { gridcolor: t.grid, zerolinecolor: t.grid, color: t.text },
      legend: { orientation: "h", y: 1.12, font: { size: 10 } },
      hoverlabel: { bgcolor: t.bg, bordercolor: t.grid, font: { color: t.text, family: "IBM Plex Mono, monospace", size: 11 } }
    };
    return Object.assign(layout, extra || {});
  }

  var DATA = null;
  var selectedExpiry = null;
  var smileMode = "side";     // "side" | "otm"
  var qualityMode = "all";    // "all" | "liquid" | "parity"

  function loadSession(path){
    document.getElementById("snapshotSub").textContent = "Loading …";
    fetch(path)
      .then(function(r){
        if(!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function(json){ DATA = json; boot(); })
      .catch(function(err){
        document.getElementById("snapshotSub").textContent =
          "Couldn't load " + path + " (" + err.message + "). " +
          "Serve this folder over HTTP (e.g. `python3 -m http.server` from web/) rather than opening index.html directly -- " +
          "browsers block local fetch() over file://.";
      });
  }

  // One-time control wiring -- runs once regardless of how many sessions get loaded.
  document.getElementById("sessionSelect").addEventListener("change", function(e){
    loadSession(e.target.value);
  });
  document.getElementById("qualitySelect").addEventListener("change", function(e){
    qualityMode = e.target.value;
    renderPerExpiry();
  });
  document.getElementById("smileToggle").addEventListener("click", function(e){
    var btn = e.target.closest("button"); if(!btn) return;
    smileMode = btn.dataset.mode;
    Array.prototype.forEach.call(this.children, function(el){ el.classList.remove("active"); });
    btn.classList.add("active");
    renderSmile(findExpiry(selectedExpiry));
  });

  loadSession(document.getElementById("sessionSelect").value);

  function boot(){
    selectedExpiry = DATA.expiries[0].expiry;
    document.getElementById("snapshotSub").textContent =
      DATA.expiries.length + " live expiries pulled from the raw archives at " + SNAP_TS() + ".";

    var sel = document.getElementById("expirySelect");
    sel.innerHTML = "";
    DATA.expiries.forEach(function(exp){
      var o = document.createElement("option");
      o.value = exp.expiry;
      o.textContent = fmtExpiry(exp.expiry) + "  (" + exp.dte_days + "d)";
      sel.appendChild(o);
    });
    sel.value = selectedExpiry;
    sel.onchange = function(){ selectedExpiry = sel.value; renderPerExpiry(); };

    renderTermAndSkew();
    renderIVSurface();
    renderPerExpiry();
  }

  function SNAP_TS(){ return DATA.snapshot_date + " " + DATA.entry_time + " IST"; }
  function fmtExpiry(e){ return e.slice(6,8)+"-"+e.slice(4,6)+"-"+e.slice(0,4); }
  function findExpiry(e){ return DATA.expiries.filter(function(x){return x.expiry===e;})[0]; }
  function fmtINR(n){ return "₹" + Math.round(n).toLocaleString("en-IN"); }

  function qualityLabel(r){
    var bits = [];
    bits.push(r.liquid ? "Liquid" : "Illiquid (<50 lots)");
    bits.push(r.parity_valid === null ? "Parity: no pair" : (r.parity_valid ? "Parity: valid" : "Parity: flagged"));
    return bits.join(" · ");
  }

  function passesQuality(r){
    if(qualityMode === "liquid") return r.liquid;
    if(qualityMode === "parity") return r.parity_valid === true;
    return true;
  }

  function filteredRows(exp){ return exp.rows.filter(passesQuality); }

  function renderPerExpiry(){
    var exp = findExpiry(selectedExpiry);
    renderSnapshotStrip(exp);
    renderSmile(exp);
    renderGreeks(exp);
    renderParity(exp);
    renderVolume(exp);
  }

  function renderSnapshotStrip(exp){
    var rows = filteredRows(exp);
    var strip = document.getElementById("snapshotStrip");
    strip.innerHTML = "";
    [
      { k: "NIFTY spot", v: fmtINR(exp.spot) },
      { k: "Timestamp", v: SNAP_TS() },
      { k: "Selected expiry", v: fmtExpiry(exp.expiry) + " (" + exp.dte_days + "d)" },
      { k: "Contracts retained / total", v: rows.length + " / " + exp.contracts_total },
      { k: "Risk-free rate", v: (DATA.risk_free * 100).toFixed(2) + "%" }
    ].forEach(function(s){
      var d = document.createElement("div");
      d.className = "stat";
      d.innerHTML = '<span class="k">'+s.k+'</span><span class="v num">'+s.v+'</span>';
      strip.appendChild(d);
    });
  }

  // Custom hover: timestamp, expiry, strike/moneyness, side, premium, IV, volume, quality.
  function rowHover(r, exp){
    return [
      SNAP_TS(),
      fmtExpiry(exp.expiry) + " (" + exp.dte_days + "d)",
      "Strike ₹" + r.strike + "  (moneyness " + r.moneyness.toFixed(3) + ")",
      r.cp === "CE" ? "Call" : "Put",
      "Premium ₹" + r.close.toFixed(2),
      "IV " + (r.iv*100).toFixed(2) + "%",
      "Volume " + r.volume + " (this minute)",
      qualityLabel(r)
    ].join("<br>");
  }

  function spotAnnotation(exp, t){
    return {
      x: exp.spot, y: 1, xref: "x", yref: "paper", xanchor: "left", yanchor: "bottom",
      text: "Spot: " + fmtINR(exp.spot), showarrow: false,
      font: { color: t.accent, size: 10, family: "IBM Plex Mono, monospace" }
    };
  }
  function spotLine(exp, t){
    return { type: "line", x0: exp.spot, x1: exp.spot, y0: 0, y1: 1, yref: "paper",
             line: { color: t.accent, width: 1, dash: "dot" } };
  }

  function emptyState(elId, t, message){
    var layout = baseLayout({
      xaxis: { visible: false }, yaxis: { visible: false },
      annotations: [{ text: message, x: 0.5, y: 0.5, xref: "paper", yref: "paper",
                      showarrow: false, font: { color: t.textFaint, size: 12 } }]
    });
    Plotly.react(elId, [], layout, {displayModeBar:false, responsive:true});
  }

  function renderSmile(exp){
    var t = theme();
    var rows = filteredRows(exp);
    if(!rows.length){ emptyState("chartSmile", t, "No contracts pass this quality filter"); return; }
    var traces, layout;

    if(smileMode === "otm"){
      var pts = otmSmile(rows);
      traces = [{
        x: pts.map(function(p){return p.r.strike;}), y: pts.map(function(p){return p.r.iv*100;}),
        mode:"lines+markers", name:"OTM composite IV",
        line:{color:t.accent,width:2}, marker:{size:5},
        text: pts.map(function(p){return rowHover(p.r, exp);}), hovertemplate: "%{text}<extra></extra>"
      }];
    } else {
      var ce = rows.filter(function(r){return r.cp==="CE";}).sort(function(a,b){return a.strike-b.strike;});
      var pe = rows.filter(function(r){return r.cp==="PE";}).sort(function(a,b){return a.strike-b.strike;});
      traces = [
        { x: ce.map(function(r){return r.strike;}), y: ce.map(function(r){return r.iv*100;}),
          mode:"lines+markers", name:"Call IV", line:{color:t.ce,width:2}, marker:{size:5},
          text: ce.map(function(r){return rowHover(r, exp);}), hovertemplate: "%{text}<extra></extra>" },
        { x: pe.map(function(r){return r.strike;}), y: pe.map(function(r){return r.iv*100;}),
          mode:"lines+markers", name:"Put IV", line:{color:t.pe,width:2}, marker:{size:5},
          text: pe.map(function(r){return rowHover(r, exp);}), hovertemplate: "%{text}<extra></extra>" }
      ];
    }
    layout = baseLayout({
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text, zeroline:false },
      yaxis:{ title:"IV (%)", gridcolor:t.grid, color:t.text },
      shapes: [spotLine(exp, t)], annotations: [spotAnnotation(exp, t)]
    });
    Plotly.react("chartSmile", traces, layout, {displayModeBar:false, responsive:true});
  }

  function renderTermAndSkew(){
    var t = theme();
    var exps = DATA.expiries.filter(function(e){return e.atm_iv!=null;});
    var dte = exps.map(function(e){return e.dte_days;});
    var atm = exps.map(function(e){return e.atm_iv*100;});
    var skew = exps.map(function(e){return e.skew_25d!=null ? e.skew_25d*100 : null;});
    var labels = exps.map(function(e){return fmtExpiry(e.expiry);});

    // Two stacked, independently-scaled panels sharing the x-axis, rather
    // than one dual-axis overlay -- ATM level and skew are different units
    // and a shared plot area invites reading their shapes as related.
    var traces = [
      { x:dte, y:atm, mode:"lines+markers", name:"ATM IV (%)", xaxis:"x", yaxis:"y",
        line:{color:t.accent,width:2}, marker:{size:7},
        text: labels.map(function(l,i){return l+"<br>ATM IV "+atm[i].toFixed(2)+"%";}), hovertemplate:"%{text}<extra></extra>" },
      { x:dte, y:skew, mode:"lines+markers", name:"25Δ skew, put−call (%)", xaxis:"x2", yaxis:"y2",
        line:{color:t.bad,width:2,dash:"dash"}, marker:{size:6},
        text: labels.map(function(l,i){return skew[i]==null?l+"<br>skew unavailable":l+"<br>25Δ skew "+skew[i].toFixed(2)+"%";}), hovertemplate:"%{text}<extra></extra>" }
    ];
    var layout = baseLayout({
      grid: { rows: 2, columns: 1, pattern: "independent", roworder: "top to bottom" },
      xaxis:  { title:"", gridcolor:t.grid, color:t.text, matches:"x2" },
      yaxis:  { title:"ATM IV (%)", gridcolor:t.grid, color:t.text, domain:[0.58,1] },
      xaxis2: { title:"Days to expiry", gridcolor:t.grid, color:t.text },
      yaxis2: { title:"Skew (%)", gridcolor:t.grid, color:t.text, domain:[0,0.42] },
      showlegend:false,
      annotations:[
        {text:"ATM IV", x:0.02, y:1, xref:"paper", yref:"paper", showarrow:false, font:{color:t.accent,size:10}},
        {text:"25Δ skew (put−call)", x:0.02, y:0.42, xref:"paper", yref:"paper", showarrow:false, font:{color:t.bad,size:10}}
      ]
    });
    Plotly.react("chartTerm", traces, layout, {displayModeBar:false, responsive:true});
  }

  function lerp(x0,y0,x1,y1,x){ return y0 + (y1-y0) * (x-x0) / (x1-x0); }

  function otmSmile(rows){
    // Standard smile construction: OTM put IV below spot, OTM call IV above --
    // avoids picking arbitrarily between two IVs quoted at the same strike.
    return rows
      .filter(function(r){ return (r.moneyness < 1 && r.cp === "PE") || (r.moneyness >= 1 && r.cp === "CE"); })
      .map(function(r){ return {m:r.moneyness, iv:r.iv*100, r:r}; })
      .sort(function(a,b){ return a.m - b.m; });
  }

  function interpAt(pts, m, maxGap){
    // Returns null (missing) rather than extrapolating past the actual
    // moneyness range this expiry traded, or across a gap wider than maxGap.
    if(m < pts[0].m - maxGap || m > pts[pts.length-1].m + maxGap) return null;
    if(m <= pts[0].m) return pts[0].iv;
    if(m >= pts[pts.length-1].m) return pts[pts.length-1].iv;
    for(var i=0;i<pts.length-1;i++){
      if(m >= pts[i].m && m <= pts[i+1].m){
        if(pts[i+1].m - pts[i].m > maxGap) return null;
        return lerp(pts[i].m, pts[i].iv, pts[i+1].m, pts[i+1].iv, m);
      }
    }
    return null;
  }

  function renderIVSurface(){
    var t = theme();
    var exps = DATA.expiries.filter(function(e){ return e.rows.length > 3; })
      .slice().sort(function(a,b){ return a.dte_days - b.dte_days; });

    var mLo = 0.85, mHi = 1.15, nM = 30, maxGap = 0.03;
    var mGrid = []; for(var i=0;i<nM;i++) mGrid.push(mLo + (mHi-mLo)*i/(nM-1));
    var yLabels = exps.map(function(e){ return fmtExpiry(e.expiry)+" ("+e.dte_days+"d)"; });

    // Only 4 expiries live that day -- too sparse a grid for a 3D surface to
    // read cleanly (a fine mesh would just be interpolation between 4 lines).
    // A heatmap shows the same moneyness x DTE x IV data without pretending
    // to more resolution than the snapshot actually has.
    var z = [], hoverText = [];
    exps.forEach(function(e){
      var pts = otmSmile(e.rows.filter(function(r){return r.iv!=null;}));
      var zRow = [], hRow = [];
      mGrid.forEach(function(m){
        var iv = pts.length ? interpAt(pts, m, maxGap) : null;
        zRow.push(iv);
        hRow.push(iv == null
          ? fmtExpiry(e.expiry)+"<br>Moneyness "+m.toFixed(3)+"<br>No data (outside traded range)"
          : fmtExpiry(e.expiry)+"<br>Moneyness "+m.toFixed(3)+"<br>Implied volatility "+iv.toFixed(2)+"%");
      });
      z.push(zRow); hoverText.push(hRow);
    });

    var finite = [].concat.apply([], z).filter(function(v){ return v != null; });
    var zmin = Math.min.apply(null, finite), zmax = Math.max.apply(null, finite);

    var trace = {
      type:"heatmap", x:mGrid, y:yLabels, z:z, text: hoverText, hoverinfo:"text",
      zmin: zmin, zmax: zmax,
      colorscale:[[0,"#20293a"],[0.25,"#39738a"],[0.55,"#8fb8c9"],[0.8,"#e8b876"],[1,"#c4685a"]],
      // NaN/null cells render as the plot background -- a distinct, neutral
      // "no data" treatment rather than a colored (and therefore falsely
      // implied-observed) extrapolation.
      colorbar:{ title:{text:"Implied volatility (%)", font:{color:t.text,size:10}}, tickfont:{color:t.text,size:9},
                 outlinecolor:t.grid, len:0.9 }
    };
    var layout = baseLayout({
      xaxis:{ title:"Moneyness (K/S)", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"", gridcolor:t.grid, color:t.text, automargin:true },
      margin:{ l:140, r:16, t:8, b:40 }
    });
    Plotly.react("chartIVSurface", [trace], layout, {displayModeBar:false, responsive:true});
  }

  var GREEK_PANELS = [
    { id:"chartDelta", key:"delta",       title:"Delta (per ₹1 move)",  scale:1,     dp:3 },
    { id:"chartGamma", key:"gamma",       title:"Gamma (per ₹1 move)",  scale:1000,  dp:4, suffix:" ×10³" },
    { id:"chartVega",  key:"vega",        title:"Vega (per 1 vol pt)",       scale:0.01,  dp:3 },
    { id:"chartTheta", key:"theta_per_day", title:"Theta (per day)",         scale:1,     dp:2 }
  ];

  function renderGreeks(exp){
    var t = theme();
    var rows = filteredRows(exp);
    if(!rows.length){
      GREEK_PANELS.forEach(function(p){ emptyState(p.id, t, "No contracts pass this quality filter"); });
      return;
    }
    var ce = rows.filter(function(r){return r.cp==="CE";}).sort(function(a,b){return a.strike-b.strike;});
    var pe = rows.filter(function(r){return r.cp==="PE";}).sort(function(a,b){return a.strike-b.strike;});

    GREEK_PANELS.forEach(function(p, idx){
      var traces = [
        { x: ce.map(function(r){return r.strike;}), y: ce.map(function(r){return r[p.key]*p.scale;}),
          name:"Call", mode:"lines+markers", line:{color:t.ce,width:2}, marker:{size:4},
          text: ce.map(function(r){return rowHover(r, exp);}), hovertemplate:"%{text}<extra></extra>" },
        { x: pe.map(function(r){return r.strike;}), y: pe.map(function(r){return r[p.key]*p.scale;}),
          name:"Put", mode:"lines+markers", line:{color:t.pe,width:2}, marker:{size:4},
          text: pe.map(function(r){return rowHover(r, exp);}), hovertemplate:"%{text}<extra></extra>" }
      ];
      var layout = baseLayout({
        margin:{ l:56, r:16, t:2, b: idx===GREEK_PANELS.length-1 ? 34 : 2 },
        xaxis:{ title: idx===GREEK_PANELS.length-1 ? "Strike" : "", gridcolor:t.grid, color:t.text,
                showticklabels: idx===GREEK_PANELS.length-1 },
        yaxis:{ title:p.title+(p.suffix||""), titlefont:{size:10}, gridcolor:t.grid, color:t.text },
        showlegend: idx===0,
        legend:{ orientation:"h", y:1.35, font:{size:10} },
        shapes:[spotLine(exp, t)]
      });
      Plotly.react(p.id, traces, layout, {displayModeBar:false, responsive:true});
    });
  }

  function renderParity(exp){
    var t = theme();
    var rows = exp.parity;
    var summary = document.getElementById("paritySummary");
    if(!rows.length){
      summary.innerHTML = "No strikes traded both legs in this minute.";
      Plotly.react("chartParity", [], baseLayout({}), {displayModeBar:false, responsive:true});
      return;
    }
    var absRes = rows.map(function(r){return Math.abs(r.residual);}).sort(function(a,b){return a-b;});
    var median = absRes[Math.floor(absRes.length/2)];
    var nValid = rows.filter(function(r){return r.valid;}).length;
    var nInvalid = rows.length - nValid;
    summary.innerHTML =
      "Median |residual| <b>" + median.toFixed(1) + " pts</b> &middot; " +
      "<b>" + nValid + " / " + rows.length + "</b> strike pairs within &plusmn;15 pt tolerance &middot; " +
      "<b>" + (100*nInvalid/rows.length).toFixed(0) + "%</b> flagged";

    var trace = {
      x: rows.map(function(r){return r.strike;}),
      y: rows.map(function(r){return r.residual;}),
      mode:"markers", type:"scatter",
      marker:{
        size: 8,
        color: rows.map(function(r){return r.valid ? t.good : t.bad;}),
        line: { color: rows.map(function(r){return r.valid ? t.good : t.bad;}), width: 1 }
      },
      text: rows.map(function(r){
        return "Strike ₹"+r.strike+"<br>Residual "+r.residual.toFixed(2)+" pts<br>"+
          "Call vol "+r.ce_vol+" · Put vol "+r.pe_vol+"<br>"+
          (r.valid ? "Within tolerance" : "Flagged: likely stale/illiquid/asynchronous, not arbitrage");
      }),
      hovertemplate: "%{text}<extra></extra>"
    };
    var layout = baseLayout({
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"Residual (pts)", gridcolor:t.grid, color:t.text, zeroline:true, zerolinecolor:t.grid },
      shapes:[
        { type:"line", x0:0, x1:1, xref:"paper", y0:15, y1:15, line:{color:t.bad,width:1,dash:"dot"} },
        { type:"line", x0:0, x1:1, xref:"paper", y0:-15, y1:-15, line:{color:t.bad,width:1,dash:"dot"} }
      ]
    });
    Plotly.react("chartParity", [trace], layout, {displayModeBar:false, responsive:true});
  }

  function renderVolume(exp){
    var t = theme();
    var rows = filteredRows(exp).slice().sort(function(a,b){return a.strike-b.strike;});
    if(!rows.length){ emptyState("chartVolume", t, "No contracts pass this quality filter"); return; }
    var ce = rows.filter(function(r){return r.cp==="CE";});
    var pe = rows.filter(function(r){return r.cp==="PE";});
    var traces = [
      { x:ce.map(function(r){return r.strike;}), y:ce.map(function(r){return r.volume;}), name:"Call", type:"bar", marker:{color:t.ce},
        text: ce.map(function(r){return rowHover(r, exp);}), hovertemplate:"%{text}<extra></extra>" },
      { x:pe.map(function(r){return r.strike;}), y:pe.map(function(r){return -r.volume;}), name:"Put (mirrored)", type:"bar", marker:{color:t.pe},
        text: pe.map(function(r){return rowHover(r, exp);}), hovertemplate:"%{text}<extra></extra>" }
    ];
    var layout = baseLayout({
      barmode:"relative",
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"Contracts traded per minute (puts mirrored)", titlefont:{size:10}, gridcolor:t.grid, color:t.text }
    });
    Plotly.react("chartVolume", traces, layout, {displayModeBar:false, responsive:true});
  }

  window.addEventListener("resize", function(){
    ["chartSmile","chartTerm","chartIVSurface","chartDelta","chartGamma","chartVega","chartTheta","chartParity","chartVolume"]
      .forEach(function(id){
        var el = document.getElementById(id);
        if(el && el.offsetParent) Plotly.Plots.resize(el);
      });
  });
})();
