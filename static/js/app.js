document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('.alert[data-auto-dismiss-ms]').forEach(alert=>{
    const delay=Number(alert.dataset.autoDismissMs);
    if(!Number.isFinite(delay)||delay<0)return;
    window.setTimeout(()=>{
      if(!alert.isConnected||!alert.classList.contains('show'))return;
      if(window.bootstrap?.Alert){
        window.bootstrap.Alert.getOrCreateInstance(alert).close();
      }else{
        alert.remove();
      }
    },delay);
  });

  const root=document.documentElement;
  const themeToggle=document.querySelector('[data-theme-toggle]');
  const applyTheme=theme=>{
    root.dataset.theme=theme;
    if(themeToggle){
      const dark=theme==='dark';
      themeToggle.setAttribute('aria-label',dark?'Switch to light mode':'Switch to dark mode');
      themeToggle.setAttribute('title',dark?'Switch to light mode':'Switch to dark mode');
      themeToggle.innerHTML=`<i class="bi ${dark?'bi-sun':'bi-moon-stars'}"></i>`;
    }
  };
  applyTheme(root.dataset.theme||'light');
  if(themeToggle)themeToggle.addEventListener('click',()=>{
    const theme=root.dataset.theme==='dark'?'light':'dark';
    applyTheme(theme);
    try{
      localStorage.setItem('cssms-theme',theme);
    }catch(error){
      console.error('Could not save the theme preference.',error);
    }
  });

  const toggle=document.getElementById('menuToggle');
  const side=document.getElementById('sidebar');
  const sidebarClose=document.getElementById('sidebarClose');
  const sidebarBackdrop=document.getElementById('sidebarBackdrop');
  const setSidebarOpen=open=>{
    if(!toggle||!side)return;
    side.classList.toggle('show',open);
    document.body.classList.toggle('sidebar-open',open);
    toggle.setAttribute('aria-expanded',String(open));
  };
  if(toggle&&side){
    toggle.setAttribute('aria-controls','sidebar');
    toggle.setAttribute('aria-expanded','false');
    toggle.addEventListener('click',()=>setSidebarOpen(!side.classList.contains('show')));
    sidebarClose?.addEventListener('click',()=>setSidebarOpen(false));
    sidebarBackdrop?.addEventListener('click',()=>setSidebarOpen(false));
    side.querySelectorAll('.nav-linkx').forEach(link=>{
      link.addEventListener('click',()=>setSidebarOpen(false));
    });
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&side.classList.contains('show'))setSidebarOpen(false);
    });
  }

  const presenceCount=document.querySelector('[data-presence-count]');
  const presenceList=document.querySelector('[data-presence-list]');
  const presenceUrl=presenceList?.dataset.presenceUrl;
  const updatePresence=async()=>{
    if(!presenceCount||!presenceList||!presenceUrl)return;
    const csrfToken=document.cookie.split('; ').find(cookie=>cookie.startsWith('csrftoken='))?.split('=').slice(1).join('=');
    if(!csrfToken){
      presenceCount.textContent='Presence unavailable';
      presenceList.textContent='Refresh the page to reconnect.';
      return;
    }
    try{
      const response=await fetch(presenceUrl,{
        method:'POST',
        credentials:'same-origin',
        headers:{'X-CSRFToken':decodeURIComponent(csrfToken),'X-Requested-With':'XMLHttpRequest'}
      });
      if(!response.ok)throw new Error(`Presence request failed (${response.status}).`);
      const data=await response.json();
      const onlineIds=new Set(data.users.map(user=>String(user.id)));
      presenceCount.textContent=`${data.users.length} online`;
      presenceList.replaceChildren();
      if(data.users.length===0){
        const empty=document.createElement('span');
        empty.className='presence-empty';
        empty.textContent='No one is online right now.';
        presenceList.append(empty);
      }else{
        data.users.forEach(user=>{
          const item=document.createElement('div');
          item.className='presence-user';
          const dot=document.createElement('span');
          dot.className='presence-indicator';
          const name=document.createElement('span');
          name.className='presence-user-name';
          name.textContent=user.full_name;
          const role=document.createElement('small');
          role.textContent=user.role;
          item.append(dot,name,role);
          presenceList.append(item);
        });
      }
      document.querySelectorAll('[data-presence-user]').forEach(status=>{
        const online=onlineIds.has(status.dataset.presenceUser);
        status.classList.toggle('is-online',online);
        status.textContent=online?'Online':'Offline';
      });
    }catch(error){
      presenceCount.textContent='Presence unavailable';
      presenceList.textContent='Could not refresh online status.';
      console.error(error);
    }
  };
  if(presenceCount&&presenceList){
    updatePresence();
    window.setInterval(()=>{if(document.visibilityState==='visible')updatePresence();},60000);
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')updatePresence();});
  }

  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-password-toggle]');
    if(!button)return;
    const input=document.getElementById(button.dataset.passwordToggle);
    if(!input)return;
    const visible=input.type==='password';
    input.type=visible?'text':'password';
    button.setAttribute('aria-label',visible?'Hide password':'Show password');
    button.setAttribute('aria-pressed',String(visible));
    const icon=button.querySelector('i');
    if(icon)icon.className=`bi ${visible?'bi-eye-slash':'bi-eye'}`;
  });

  document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{
    const b=f.querySelector('button[type=submit],button:not([type])');
    if(b&&b.dataset.loading!=='off'){
      b.dataset.original=b.innerHTML;
      b.innerHTML='<span class="spinner-border spinner-border-sm me-2"></span>Processing...';
      b.disabled=true;
    }
  }));
});