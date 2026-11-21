(function(){
  var fig=document.getElementById('dayfig'); if(!fig) return;
  var plot=fig.querySelector('.plot'), tip=fig.querySelector('.tip'), cols=fig.querySelectorAll('.colm'), cur=null;
  function n(v){return Number(v).toLocaleString('en-US')}
  function p2(h){return (h<10?'0':'')+h+':00'}
  function row(label,v){return '<span>'+label+'<u>'+n(v)+' kW</u></span>'}
  function show(c){
    if(cur&&cur!==c) cur.classList.remove('on');
    cur=c; c.classList.add('on');
    var d=c.dataset, h=+d.h;
    tip.innerHTML='<b>'+p2(h)+' to '+p2((h+1)%24)+'</b>'+row('Community',d.t)+row('Other use',d.ot)+row('Shops',d.sh)+row('Office',d.of)+row('Our 200 homes',d.hm);
    tip.hidden=false;
    var w=tip.offsetWidth/2, x=c.offsetLeft+c.offsetWidth/2, max=plot.clientWidth;
    tip.style.left=Math.max(w,Math.min(max-w,x))+'px';
  }
  function hide(){ if(cur) cur.classList.remove('on'); cur=null; tip.hidden=true; }
  cols.forEach(function(c){
    c.addEventListener('pointerenter',function(){show(c)});
    c.addEventListener('focus',function(){show(c)});
    c.addEventListener('click',function(){show(c)});
    c.addEventListener('blur',hide);
  });
  plot.addEventListener('pointerleave',hide);
})();
