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

  var state = { qty:"price", side:"CE", axes:"S_T", S0:24500, K:24500, Tdays:30, sigma:14, r:6.5 };

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
    K:     {label:"Strike (K)",           min:20000, max:29000, step:50,  fmt:function(v){return "₹"+v.toLocaleString("en-IN");}},
    Tdays: {label:"Time to expiry",       min:1,     max:180,   step:1,   fmt:function(v){return v+" d";}},
    sigma: {label:"Implied volatility",   min:5,     max:60,    step:0.5, fmt:function(v){return v.toFixed(1)+"%";}},
    r:     {label:"Risk-free rate",       min:0,     max:12,    step:0.25,fmt:function(v){return v.toFixed(2)+"%";}}
  };
  var SLIDERS_FOR_AXES = { S_T:["K","sigma","r"], S_K:["Tdays","sigma","r"], S_V:["K","Tdays","r"] };
  function buildSliders(){
    var box = document.getElementById("sliders");
    box.innerHTML = "";
    SLIDERS_FOR_AXES[state.axes].forEach(function(key){
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
      {k:"spot (fixed at)", v: "₹"+state.S0.toLocaleString("en-IN")}
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

  buildSliders();
  render();
  window.addEventListener("resize", function(){
    var el = document.getElementById("surface");
    if(el && el.offsetParent) Plotly.Plots.resize(el);
  });
})();
