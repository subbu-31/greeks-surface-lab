(function(){
  "use strict";
  var root = document.documentElement;
  function cssVar(name){ return getComputedStyle(root).getPropertyValue(name).trim(); }
  function theme(){
    return {
      text: cssVar("--text"), grid: cssVar("--border"), bg: cssVar("--surface"),
      ce: cssVar("--ce"), pe: cssVar("--pe"), accent: cssVar("--accent"),
      delta: cssVar("--delta"), gamma: cssVar("--gamma"), vega: cssVar("--vega"), bad: cssVar("--bad")
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
      legend: { orientation: "h", y: 1.12, font: { size: 10 } }
    };
    return Object.assign(layout, extra || {});
  }

  var DATA = null;
  var selectedExpiry = null;

  fetch("data/market_snapshot.json")
    .then(function(r){
      if(!r.ok) throw new Error("http " + r.status);
      return r.json();
    })
    .then(function(json){ DATA = json; boot(); })
    .catch(function(err){
      document.getElementById("snapshotSub").textContent =
        "Couldn't load data/market_snapshot.json (" + err.message + "). " +
        "Serve this folder over HTTP (e.g. `python3 -m http.server` from web/) rather than opening index.html directly -- " +
        "browsers block local fetch() over file://.";
    });

  function boot(){
    selectedExpiry = DATA.expiries[0].expiry;
    document.getElementById("snapshotSub").textContent =
      "Snapshot: " + DATA.snapshot_date + " at " + DATA.entry_time + " IST — " +
      DATA.expiries.length + " live expiries pulled from the raw archives, r = " + (DATA.risk_free*100).toFixed(1) + "%.";

    var picker = document.getElementById("expiryPicker");
    DATA.expiries.forEach(function(exp){
      var b = document.createElement("button");
      b.className = "seg-btn" + (exp.expiry === selectedExpiry ? " active" : "");
      b.textContent = fmtExpiry(exp.expiry) + " (" + exp.dte_days + "d)";
      b.addEventListener("click", function(){
        selectedExpiry = exp.expiry;
        Array.prototype.forEach.call(picker.children, function(el){ el.classList.remove("active"); });
        b.classList.add("active");
        renderPerExpiry();
      });
      picker.appendChild(b);
    });

    renderTermAndSkew();
    renderIVSurface();
    renderPerExpiry();
  }

  function fmtExpiry(e){ return e.slice(6,8)+"-"+e.slice(4,6)+"-"+e.slice(0,4); }
  function findExpiry(e){ return DATA.expiries.filter(function(x){return x.expiry===e;})[0]; }

  function renderPerExpiry(){
    var exp = findExpiry(selectedExpiry);
    renderSmile(exp);
    renderGreeks(exp);
    renderParity(exp);
    renderVolume(exp);
  }

  function renderSmile(exp){
    var t = theme();
    var ce = exp.rows.filter(function(r){return r.cp==="CE";});
    var pe = exp.rows.filter(function(r){return r.cp==="PE";});
    var traces = [
      { x: ce.map(function(r){return r.strike;}), y: ce.map(function(r){return r.iv*100;}),
        mode:"lines+markers", name:"Call IV", line:{color:t.ce,width:2}, marker:{size:5} },
      { x: pe.map(function(r){return r.strike;}), y: pe.map(function(r){return r.iv*100;}),
        mode:"lines+markers", name:"Put IV", line:{color:t.pe,width:2}, marker:{size:5} }
    ];
    var layout = baseLayout({
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text, zeroline:false },
      yaxis:{ title:"IV (%)", gridcolor:t.grid, color:t.text }
    });
    layout.shapes = [{ type:"line", x0:exp.spot, x1:exp.spot, y0:0, y1:1, yref:"paper",
                       line:{color:t.accent, width:1, dash:"dot"} }];
    Plotly.react("chartSmile", traces, layout, {displayModeBar:false, responsive:true});
  }

  function renderTermAndSkew(){
    var t = theme();
    var exps = DATA.expiries.filter(function(e){return e.atm_iv!=null;});
    var dte = exps.map(function(e){return e.dte_days;});
    var atm = exps.map(function(e){return e.atm_iv*100;});
    var skew = exps.map(function(e){return e.skew_25d!=null ? e.skew_25d*100 : null;});
    var traces = [
      { x:dte, y:atm, mode:"lines+markers", name:"ATM IV (%)", yaxis:"y",
        line:{color:t.accent,width:2}, marker:{size:7} },
      { x:dte, y:skew, mode:"lines+markers", name:"25Δ skew, put−call (%)", yaxis:"y2",
        line:{color:t.bad,width:2,dash:"dash"}, marker:{size:6} }
    ];
    var layout = baseLayout({
      xaxis:{ title:"Days to expiry", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"ATM IV (%)", gridcolor:t.grid, color:t.text },
      yaxis2:{ title:"Skew (%)", overlaying:"y", side:"right", gridcolor:"transparent", color:t.text }
    });
    Plotly.react("chartTerm", traces, layout, {displayModeBar:false, responsive:true});
  }

  function lerp(x0,y0,x1,y1,x){ return y0 + (y1-y0) * (x-x0) / (x1-x0); }

  function otmSmile(exp){
    // Standard smile construction: OTM put IV below spot, OTM call IV above --
    // avoids picking arbitrarily between two IVs quoted at the same strike.
    var pts = exp.rows
      .filter(function(r){ return (r.moneyness < 1 && r.cp === "PE") || (r.moneyness >= 1 && r.cp === "CE"); })
      .map(function(r){ return {m:r.moneyness, iv:r.iv*100}; })
      .sort(function(a,b){ return a.m - b.m; });
    return pts;
  }

  function interpAt(pts, m){
    if(m <= pts[0].m) return pts[0].iv;
    if(m >= pts[pts.length-1].m) return pts[pts.length-1].iv;
    for(var i=0;i<pts.length-1;i++){
      if(m >= pts[i].m && m <= pts[i+1].m) return lerp(pts[i].m, pts[i].iv, pts[i+1].m, pts[i+1].iv, m);
    }
    return pts[pts.length-1].iv;
  }

  function renderIVSurface(){
    var t = theme();
    var exps = DATA.expiries.filter(function(e){ return e.rows.length > 3; })
      .slice().sort(function(a,b){ return a.dte_days - b.dte_days; });

    var mLo = 0.85, mHi = 1.15, nM = 30;
    var mGrid = []; for(var i=0;i<nM;i++) mGrid.push(mLo + (mHi-mLo)*i/(nM-1));
    var yDte = exps.map(function(e){ return e.dte_days; });
    var z = exps.map(function(e){
      var pts = otmSmile(e);
      return mGrid.map(function(m){ return interpAt(pts, m); });
    });

    // Only 4 expiries live that day -- too sparse a grid for a 3D surface to
    // read cleanly (a fine mesh would just be interpolation between 4 lines).
    // A heatmap shows the same moneyness x DTE x IV data without pretending
    // to more resolution than the snapshot actually has.
    var yLabels = exps.map(function(e){ return fmtExpiry(e.expiry)+" ("+e.dte_days+"d)"; });
    var trace = { type:"heatmap", x:mGrid, y:yLabels, z:z,
      colorscale:[[0,"#171d29"],[0.5,"#725d82"],[1,"#e8b876"]],
      colorbar:{ title:"IV %", titlefont:{color:t.text,size:10}, tickfont:{color:t.text,size:9},
                 outlinecolor:t.grid, len:0.9 }
    };
    var layout = baseLayout({
      xaxis:{ title:"Moneyness (K/S)", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"", gridcolor:t.grid, color:t.text, automargin:true },
      margin:{ l:140, r:16, t:8, b:40 }
    });
    Plotly.react("chartIVSurface", [trace], layout, {displayModeBar:false, responsive:true});
  }

  function renderGreeks(exp){
    var t = theme();
    var rows = exp.rows.slice().sort(function(a,b){return a.strike-b.strike;});
    var strikes = rows.map(function(r){return r.strike;});
    var traces = [
      { x:strikes, y:rows.map(function(r){return r.delta;}), name:"Delta", yaxis:"y",
        mode:"lines", line:{color:t.delta,width:2} },
      { x:strikes, y:rows.map(function(r){return r.gamma*1000;}), name:"Gamma (×1000)", yaxis:"y2",
        mode:"lines", line:{color:t.gamma,width:2} },
      { x:strikes, y:rows.map(function(r){return r.vega/100;}), name:"Vega (/1%)", yaxis:"y2",
        mode:"lines", line:{color:t.vega,width:2,dash:"dot"} }
    ];
    var layout = baseLayout({
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"Delta", gridcolor:t.grid, color:t.text },
      yaxis2:{ title:"Gamma / Vega", overlaying:"y", side:"right", gridcolor:"transparent", color:t.text }
    });
    layout.shapes = [{ type:"line", x0:exp.spot, x1:exp.spot, y0:0, y1:1, yref:"paper",
                       line:{color:t.accent, width:1, dash:"dot"} }];
    Plotly.react("chartGreeks", traces, layout, {displayModeBar:false, responsive:true});
  }

  function renderParity(exp){
    var t = theme();
    var rows = exp.parity;
    var trace = {
      x: rows.map(function(r){return r.strike;}),
      y: rows.map(function(r){return r.residual;}),
      mode:"markers", type:"scatter",
      marker:{ size:7, color: rows.map(function(r){return Math.min(r.ce_vol,r.pe_vol);}),
               colorscale:[[0,t.bad],[1,t.accent]], showscale:false }
    };
    var layout = baseLayout({
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"Residual (pts)", gridcolor:t.grid, color:t.text, zeroline:true, zerolinecolor:t.grid }
    });
    Plotly.react("chartParity", [trace], layout, {displayModeBar:false, responsive:true});
  }

  function renderVolume(exp){
    var t = theme();
    var rows = exp.rows.slice().sort(function(a,b){return a.strike-b.strike;});
    var ce = rows.filter(function(r){return r.cp==="CE";});
    var pe = rows.filter(function(r){return r.cp==="PE";});
    var traces = [
      { x:ce.map(function(r){return r.strike;}), y:ce.map(function(r){return r.volume;}), name:"Call volume", type:"bar", marker:{color:t.ce} },
      { x:pe.map(function(r){return r.strike;}), y:pe.map(function(r){return -r.volume;}), name:"Put volume", type:"bar", marker:{color:t.pe} }
    ];
    var layout = baseLayout({
      barmode:"relative",
      xaxis:{ title:"Strike", gridcolor:t.grid, color:t.text },
      yaxis:{ title:"Contracts traded (that minute)", gridcolor:t.grid, color:t.text }
    });
    Plotly.react("chartVolume", traces, layout, {displayModeBar:false, responsive:true});
  }

  window.addEventListener("resize", function(){
    ["chartSmile","chartTerm","chartIVSurface","chartGreeks","chartParity","chartVolume"].forEach(function(id){
      var el = document.getElementById(id);
      if(el && el.offsetParent) Plotly.Plots.resize(el);
    });
  });
})();
