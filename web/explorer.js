(function(){
  "use strict";

  // ---------- Black-Scholes core (mirrors bs_solver/black_scholes.py) ----------
  function nd(x){ return 0.5 * (1 + erf(x / Math.SQRT2)); }
  function npdf(x){ return Math.exp(-0.5*x*x) / Math.sqrt(2*Math.PI); }
  function erf(x){
    // Abramowitz-Stegun 7.1.26, ~1.5e-7 max error -- plenty for a visual surface
    var sign = x < 0 ? -1 : 1; x = Math.abs(x);
    var a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;
    var t = 1/(1+p*x);
    var y = 1-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);
    return sign*y;
  }
  function d1d2(S,K,T,sig,r){
    var d1=(Math.log(S/K)+(r+0.5*sig*sig)*T)/(sig*Math.sqrt(T));
    return [d1, d1-sig*Math.sqrt(T)];
  }
  var BS = {
    price:function(S,K,T,sig,cp,r){
      if(T<=0||sig<=0) return cp==="CE"? Math.max(0,S-K) : Math.max(0,K-S);
      var d=d1d2(S,K,T,sig,r), d1=d[0], d2=d[1];
      return cp==="CE" ? S*nd(d1)-K*Math.exp(-r*T)*nd(d2) : K*Math.exp(-r*T)*nd(-d2)-S*nd(-d1);
    },
    delta:function(S,K,T,sig,cp,r){
      if(T<=0||sig<=0) return cp==="CE" ? (S>K?1:0) : (S<K?-1:0);
      var d1=d1d2(S,K,T,sig,r)[0];
      return cp==="CE" ? nd(d1) : nd(d1)-1;
    },
    gamma:function(S,K,T,sig,r){
      if(T<=0||sig<=0) return 0;
      var d1=d1d2(S,K,T,sig,r)[0];
      return npdf(d1)/(S*sig*Math.sqrt(T));
    },
    vega:function(S,K,T,sig,r){
      if(T<=0||sig<=0) return 0;
      var d1=d1d2(S,K,T,sig,r)[0];
      return S*npdf(d1)*Math.sqrt(T);
    },
    theta:function(S,K,T,sig,cp,r){
      if(T<=0||sig<=0) return 0;
      var d=d1d2(S,K,T,sig,r), d1=d[0], d2=d[1];
      var decay = -(S*npdf(d1)*sig)/(2*Math.sqrt(T));
      return cp==="CE" ? decay - r*K*Math.exp(-r*T)*nd(d2) : decay + r*K*Math.exp(-r*T)*nd(-d2);
    },
    rho:function(S,K,T,sig,cp,r){
      if(T<=0||sig<=0) return 0;
      var d2=d1d2(S,K,T,sig,r)[1];
      return cp==="CE" ? K*T*Math.exp(-r*T)*nd(d2) : -K*T*Math.exp(-r*T)*nd(-d2);
    }
  };

  if (typeof module !== "undefined" && module.exports) {
    // Node (tests/test_js_parity.py shells out to node to check this
    // object against bs_solver/black_scholes.py) -- everything below this
    // block touches the DOM and Plotly, neither of which exist there.
    module.exports = BS;
    return;
  }

  var QUANTITIES = [
    {id:"price", label:"Price", color:"--price", fmt:function(v){return "₹"+v.toFixed(1);}},
    {id:"delta", label:"Delta", color:"--delta", fmt:function(v){return v.toFixed(3);}},
    {id:"gamma", label:"Gamma", color:"--gamma", fmt:function(v){return v.toFixed(5);}},
    {id:"vega",  label:"Vega",  color:"--vega",  fmt:function(v){return (v/100).toFixed(2)+" /1%";}},
    {id:"theta", label:"Theta", color:"--theta", fmt:function(v){return (v/365).toFixed(2)+" /day";}},
    {id:"rho",   label:"Rho",   color:"--rho",   fmt:function(v){return (v/100).toFixed(3)+" /1%";}}
  ];
  var AXES = {
    S_T: {x:"Spot", y:"Time to expiry (days)"},
    S_K: {x:"Spot", y:"Strike"},
    S_V: {x:"Spot", y:"Implied vol (%)"}
  };

  // Calendar mode reuses the real dashboard's own two sessions and seven
  // hourly checkpoints, rather than a free-form date/time picker -- this
  // solver has no live or minute-level feed behind it (nothing here
  // "updates" between checkpoints), so offering minute-by-minute entry
  // times or arbitrary dates would imply a precision that doesn't exist.
  // Expiries are each session's own real live expiries (build_market_snapshot.py).
  var SESSIONS = [
    { date:"2024-12-27", label:"2024-12-27", expiries:["2025-01-02","2025-01-09","2025-01-16","2025-01-23"] },
    { date:"2026-03-11", label:"2026-03-11 (Thu→Tue expiry day)", expiries:["2026-03-17","2026-03-24","2026-03-30","2026-04-07"] }
  ];
  var ENTRY_HOURS = ["09:15","10:15","11:15","12:15","13:15","14:15","15:15"];

  function sessionFor(date){
    return SESSIONS.filter(function(s){ return s.date === date; })[0] || SESSIONS[0];
  }
  function fmtIsoDMY(iso){ var p = iso.split("-"); return p[2]+"-"+p[1]+"-"+p[0]; }

  var state = {
    qty:"price", side:"CE", axes:"S_T", S0:24500, K:24500, Tdays:30, sigma:14, r:6.5,
    // "Time to expiry" can be set two ways: a plain days slider, or the same
    // session/hour/expiry the real NIFTY dashboard uses (bs_solver.rates'
    // years_to_expiry marks expiry at 15:30 local) -- defaults match that
    // dashboard's own unified session, so the two tabs agree on what
    // "13.26 days" actually means.
    dateMode:"days", entryDate:SESSIONS[0].date, entryTime:"09:15", expiryDate:"2025-01-09"
  };

  var root = document.documentElement;
  function cssVar(name){ return getComputedStyle(root).getPropertyValue(name).trim(); }

  var qtyGrid = document.getElementById("qtyGrid");
  QUANTITIES.forEach(function(q){
    var b = document.createElement("button");
    b.className = "qty-btn" + (q.id===state.qty ? " active":"");
    b.style.setProperty("--qty-color", "var("+q.color+")");
    b.innerHTML = '<span class="dot" style="background:var('+q.color+')"></span><span class="lbl">'+q.label+'</span>';
    b.addEventListener("click", function(){
      state.qty = q.id;
      Array.prototype.forEach.call(qtyGrid.children, function(el){ el.classList.remove("active"); });
      b.classList.add("active");
      render();
    });
    qtyGrid.appendChild(b);
  });

  document.getElementById("sideRow").addEventListener("click", function(e){
    var btn = e.target.closest(".seg-btn"); if(!btn) return;
    state.side = btn.dataset.side;
    Array.prototype.forEach.call(this.children, function(el){ el.classList.remove("active"); });
    btn.classList.add("active");
    render();
  });

  var axesRows = document.querySelectorAll("[data-axes]");
  axesRows.forEach(function(btn){
    btn.addEventListener("click", function(){
      state.axes = btn.dataset.axes;
      axesRows.forEach(function(el){ el.classList.remove("active"); });
      btn.classList.add("active");
      buildSliders();
      render();
    });
  });

  var SLIDER_DEFS = {
    S0:    {label:"Spot (center)",         min:15000, max:35000, step:50,  fmt:function(v){return "₹"+v.toLocaleString("en-IN");}},
    K:     {label:"Strike (K)",           min:20000, max:29000, step:50,  fmt:function(v){return "₹"+v.toLocaleString("en-IN");}},
    Tdays: {label:"Time to expiry",       min:1,     max:180,   step:1,   fmt:function(v){return v+" d";}},
    sigma: {label:"Implied volatility",   min:5,     max:60,    step:0.5, fmt:function(v){return v.toFixed(1)+"%";}},
    r:     {label:"Risk-free rate",       min:0,     max:12,    step:0.25,fmt:function(v){return v.toFixed(2)+"%";}}
  };
  var SLIDERS_FOR_AXES = { S_T:["K","sigma","r"], S_K:["Tdays","sigma","r"], S_V:["K","Tdays","r"] };

  // Spot is always a plotted axis, not a fixed parameter, so its slider
  // lives in its own always-visible panel (spotSlider) rather than the
  // axis-dependent "Fixed parameters" list built by buildSliders() below --
  // it sets where that axis's visible 0.7x-1.3x window is centered, same
  // meaning in all three axis modes.
  function buildSpotSlider(){
    var def = SLIDER_DEFS.S0;
    var box = document.getElementById("spotSlider");
    var row = document.createElement("div");
    row.className = "slider-row";
    row.innerHTML =
      '<div class="slider-head"><span class="name">'+def.label+'</span><span class="val num" id="val_S0">'+def.fmt(state.S0)+'</span></div>'+
      '<input type="range" id="sl_S0" min="'+def.min+'" max="'+def.max+'" step="'+def.step+'" value="'+state.S0+'">';
    box.appendChild(row);
    var input = row.querySelector("input");
    input.addEventListener("input", function(){
      state.S0 = parseFloat(input.value);
      document.getElementById("val_S0").textContent = def.fmt(state.S0);
      render();
    });
  }

  // Real days between an entry timestamp and expiry -- expiry marked at
  // 15:30 local, the same convention bs_solver.rates and the market-data
  // scripts use, not midnight.
  function daysBetween(entryDate, entryTime, expiryDate){
    var entry = new Date(entryDate + "T" + entryTime + ":00");
    var exp = new Date(expiryDate + "T15:30:00");
    return (exp.getTime() - entry.getTime()) / 86400000;
  }

  function buildSliders(){
    var box = document.getElementById("sliders");
    box.innerHTML = "";
    if(state.axes === "S_T"){
      var note = document.createElement("div");
      note.className = "axis-note";
      note.textContent = "Time to expiry is this surface's own axis (1-180d) here -- switch to Spot × Strike or Spot × Volatility to fix it instead, with a Days/Calendar toggle.";
      box.appendChild(note);
    }
    SLIDERS_FOR_AXES[state.axes].forEach(function(key){
      if(key === "Tdays"){ box.appendChild(buildTdaysControl()); return; }
      var def = SLIDER_DEFS[key];
      var row = document.createElement("div");
      row.className = "slider-row";
      row.innerHTML =
        '<div class="slider-head"><span class="name">'+def.label+'</span><span class="val num" id="val_'+key+'">'+def.fmt(state[key])+'</span></div>'+
        '<input type="range" id="sl_'+key+'" min="'+def.min+'" max="'+def.max+'" step="'+def.step+'" value="'+state[key]+'">';
      box.appendChild(row);
      var input = row.querySelector("input");
      input.addEventListener("input", function(){
        state[key] = parseFloat(input.value);
        document.getElementById("val_"+key).textContent = def.fmt(state[key]);
        render();
      });
    });
  }

  function buildTdaysControl(){
    var def = SLIDER_DEFS.Tdays;
    var wrap = document.createElement("div");
    wrap.className = "slider-row";

    var toggle = document.createElement("div");
    toggle.className = "seg-row";
    toggle.style.marginBottom = "8px";
    [["days","Days"],["calendar","Calendar"]].forEach(function(pair){
      var b = document.createElement("button");
      b.className = "seg-btn" + (state.dateMode===pair[0] ? " active" : "");
      b.textContent = pair[1];
      b.addEventListener("click", function(){
        if(state.dateMode === pair[0]) return;
        state.dateMode = pair[0];
        buildSliders();
        render();
      });
      toggle.appendChild(b);
    });
    wrap.appendChild(toggle);

    if(state.dateMode === "days"){
      var head = document.createElement("div");
      head.className = "slider-head";
      head.innerHTML = '<span class="name">'+def.label+'</span><span class="val num" id="val_Tdays">'+def.fmt(state.Tdays)+'</span>';
      wrap.appendChild(head);
      var input = document.createElement("input");
      input.type = "range"; input.id = "sl_Tdays";
      input.min = String(def.min); input.max = String(def.max); input.step = String(def.step);
      input.value = String(state.Tdays);
      input.addEventListener("input", function(){
        state.Tdays = parseFloat(input.value);
        document.getElementById("val_Tdays").textContent = def.fmt(state.Tdays);
        render();
      });
      wrap.appendChild(input);
      return wrap;
    }

    // Calendar mode: Session and Expiry are each session's own real live
    // expiries (build_market_snapshot.py), and Entry time is the same
    // seven hourly checkpoints the real dashboard exposes -- not a
    // free-form date/minute picker. Nothing behind this solver updates
    // between those checkpoints, so a finer picker would only imply a
    // precision this synthetic surface doesn't have.
    function selectField(labelText, options, value, onChange){
      var f = document.createElement("div");
      f.className = "date-field";
      var lab = document.createElement("label");
      lab.textContent = labelText;
      var sel = document.createElement("select");
      sel.className = "time-input";
      options.forEach(function(opt){
        var o = document.createElement("option");
        o.value = opt.value; o.textContent = opt.label;
        if(opt.value === value) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener("change", onChange);
      f.appendChild(lab); f.appendChild(sel);
      return f;
    }

    var computed = document.createElement("div");
    computed.className = "slider-head";
    computed.style.marginTop = "2px";

    function refreshComputed(){
      var raw = daysBetween(state.entryDate, state.entryTime, state.expiryDate);
      state.Tdays = Math.min(Math.max(raw, def.min), def.max);
      var note = Math.abs(raw - state.Tdays) > 0.005
        ? ' <span style="color:var(--bad)">(clamped to '+def.min+'-'+def.max+'d)</span>' : "";
      computed.innerHTML = '<span class="name">Time to expiry</span><span class="val num">'+raw.toFixed(2)+' d'+note+'</span>';
      render();
    }

    var session = sessionFor(state.entryDate);

    wrap.appendChild(selectField("Session",
      SESSIONS.map(function(s){ return {value:s.date, label:s.label}; }),
      state.entryDate, function(e){
        state.entryDate = e.target.value;
        state.expiryDate = sessionFor(state.entryDate).expiries[0]; // reconcile, same as the market dashboard's Session -> Expiry reset
        buildSliders();
        render();
      }));

    wrap.appendChild(selectField("Entry hour",
      ENTRY_HOURS.map(function(h){ return {value:h, label:h+" IST"}; }),
      state.entryTime, function(e){
        state.entryTime = e.target.value; refreshComputed();
      }));

    wrap.appendChild(selectField("Expiry",
      session.expiries.map(function(d){ return {value:d, label:fmtIsoDMY(d)}; }),
      state.expiryDate, function(e){
        state.expiryDate = e.target.value; refreshComputed();
      }));

    wrap.appendChild(computed);
    refreshComputed();
    return wrap;
  }

  function computeGrid(){
    var n = 46;
    var axes = state.axes;
    var r = state.r/100;
    var xs = [];
    var sLo = state.S0*0.7, sHi = state.S0*1.3;
    for(var i=0;i<n;i++) xs.push(sLo + (sHi-sLo)*i/(n-1));

    var yLabelVals = [];
    if(axes==="S_T"){ for(var j=0;j<n;j++) yLabelVals.push(1+(180-1)*j/(n-1)); }
    else if(axes==="S_K"){ var kLo=state.S0*0.75,kHi=state.S0*1.25; for(var j2=0;j2<n;j2++) yLabelVals.push(kLo+(kHi-kLo)*j2/(n-1)); }
    else { for(var j3=0;j3<n;j3++) yLabelVals.push(5+(60-5)*j3/(n-1)); }

    var zs = [];
    for(var yi=0; yi<n; yi++){
      var row = [];
      for(var xi=0; xi<n; xi++){
        var S = xs[xi], K, T, sig;
        if(axes==="S_T"){ K=state.K; T=yLabelVals[yi]/365; sig=state.sigma/100; }
        else if(axes==="S_K"){ K=yLabelVals[yi]; T=state.Tdays/365; sig=state.sigma/100; }
        else { K=state.K; T=state.Tdays/365; sig=yLabelVals[yi]/100; }
        row.push(evalQty(state.qty, S, K, T, sig, state.side, r));
      }
      zs.push(row);
    }
    return {x:xs, y:yLabelVals, z:zs};
  }
  function evalQty(qty,S,K,T,sig,side,r){
    switch(qty){
      case "price": return BS.price(S,K,T,sig,side,r);
      case "delta": return BS.delta(S,K,T,sig,side,r);
      case "gamma": return BS.gamma(S,K,T,sig,r);
      case "vega":  return BS.vega(S,K,T,sig,r);
      case "theta": return BS.theta(S,K,T,sig,side,r);
      case "rho":   return BS.rho(S,K,T,sig,side,r);
    }
  }

  var COLORSCALES = {
    price: [[0,"#171d29"],[0.5,"#8a6a35"],[1,"#e8b876"]],
    delta: [[0,"#171d29"],[0.5,"#8a6a35"],[1,"#e8b876"]],
    gamma: [[0,"#171d29"],[0.5,"#4d6f7e"],[1,"#8fb8c9"]],
    vega:  [[0,"#171d29"],[0.5,"#725d82"],[1,"#b79cc9"]],
    theta: [[0,"#e8b876"],[0.5,"#171d29"],[1,"#c4685a"]],
    rho:   [[0,"#171d29"],[0.5,"#565f6d"],[1,"#8b93a3"]]
  };

  function render(){
    var qDef = QUANTITIES.filter(function(q){return q.id===state.qty;})[0];
    var ax = AXES[state.axes];
    var g = computeGrid();

    document.querySelectorAll(".qty-btn").forEach(function(el,i){
      el.classList.toggle("active", QUANTITIES[i].id===state.qty);
    });
    document.getElementById("titleLine").innerHTML =
      (state.side==="CE"?"Call":"Put") + " <span class=\"q\" style=\"--qty-color:var("+qDef.color+")\">"+qDef.label+"</span> surface";
    document.getElementById("titleLine").style.setProperty("--qty-color","var("+qDef.color+")");
    document.getElementById("axisLine").textContent = ax.x + " × " + ax.y;
    document.getElementById("rTag").textContent = state.r.toFixed(2)+"%";
    document.getElementById("calendarTag").textContent =
      (state.axes !== "S_T" && state.dateMode === "calendar")
        ? state.entryDate+" "+state.entryTime+" → "+state.expiryDate
        : "";

    var flat = [].concat.apply([], g.z);
    var atS = Math.round((g.x.length-1)/2);
    var atY = Math.round((g.y.length-1)/2);
    var atVal = g.z[atY][atS];
    var minV = Math.min.apply(null, flat), maxV = Math.max.apply(null, flat);

    var strip = document.getElementById("statStrip");
    strip.innerHTML = "";
    [
      {k:"at-the-money value", v: qDef.fmt(atVal), cls: atVal<0?"neg":(atVal>0?"pos":"")},
      {k:"surface min", v: qDef.fmt(minV)},
      {k:"surface max", v: qDef.fmt(maxV)},
      {k:"spot range centered at", v: "₹"+state.S0.toLocaleString("en-IN")}
    ].forEach(function(s){
      var d = document.createElement("div");
      d.className = "stat";
      d.innerHTML = '<span class="k">'+s.k+'</span><span class="v num '+(s.cls||"")+'">'+s.v+'</span>';
      strip.appendChild(d);
    });

    var textColor = cssVar("--text");
    var gridColor = cssVar("--border");
    var bgColor = cssVar("--surface");

    var data = [{
      type:"surface",
      x:g.x, y:g.y, z:g.z,
      colorscale: COLORSCALES[state.qty],
      showscale:false,
      contours:{ z:{show:true, usecolormap:true, project:{z:true}, width:1} },
      lighting:{ ambient:0.55, diffuse:0.65, roughness:0.9, specular:0.15 }
    }];
    var layout = {
      paper_bgcolor: bgColor, plot_bgcolor: bgColor,
      margin:{l:0,r:0,t:6,b:0},
      font:{ family:"IBM Plex Mono, monospace", color:textColor, size:11 },
      scene:{
        xaxis:{ title:ax.x, color:textColor, gridcolor:gridColor, backgroundcolor:bgColor, zerolinecolor:gridColor },
        yaxis:{ title:ax.y, color:textColor, gridcolor:gridColor, backgroundcolor:bgColor, zerolinecolor:gridColor },
        zaxis:{ title:qDef.label, color:textColor, gridcolor:gridColor, backgroundcolor:bgColor, zerolinecolor:gridColor },
        camera:{ eye:{x:1.5, y:-1.7, z:0.9} }
      }
    };
    Plotly.react("surface", data, layout, {displayModeBar:false, responsive:true});
  }

  buildSpotSlider();
  buildSliders();
  render();
  window.addEventListener("resize", function(){
    var el = document.getElementById("surface");
    if(el && el.offsetParent) Plotly.Plots.resize(el);
  });
})();
