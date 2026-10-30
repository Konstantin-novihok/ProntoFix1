/* Notification inbox + administrator broadcast and reusable templates. */
'use strict';
route('notifications', async () => {
  const admin = isAdmin();
  const inbox = await api('GET', '/notifications?limit=100');
  let templates = [], users = [], groups = [];
  if (admin) {
    try { templates = await api('GET', '/notifications/templates'); } catch (_) {}
    try { users = await api('GET', '/users'); } catch (_) {}\n    try { groups = await api('GET', '/notifications/groups'); } catch (_) {}
  }
  const cards = inbox.slice().reverse().map(n => h('article', {class:'card', style:n.priority==='critical'?'border:2px solid var(--bad)':''},
    h('div',{class:'row'},h('b',{},n.title),h('span',{class:'muted small'},n.priority.toUpperCase())),
    h('p',{},n.body),h('div',{class:'muted small'},n.category+' · '+fmtDate(n.created_at)),
    n.acknowledged_at ? h('span',{class:'muted small'},'✓ '+t('acknowledged')) :
      h('button',{onclick:guard(async()=>{await api('POST','/notifications/'+n.id+'/ack',{});toast(t('acknowledged'));render();})},t('ack_read'))));
  const children=[h('h1',{},'🔔 '+t('notifications')),h('h2',{},t('inbox')||'Входящие'),...(cards.length?cards:[h('p',{class:'muted'},t('no_notifications')||'Нет уведомлений')])];
  if(admin){
    const title=h('input',{placeholder:'Заголовок',maxLength:160});
    const body=h('textarea',{placeholder:'Текст уведомления',rows:4});
    const category=h('select',{},...['general','orders','safety','finance','system'].map(x=>h('option',{value:x},x)));
    const priority=h('select',{},...['normal','important','critical'].map(x=>h('option',{value:x},x)));
    const snd=h('input',{type:'checkbox'});snd.type='checkbox';
    const roles=h('select',{multiple:true,size:5},...[[1,'Владелец'],[2,'Руководитель'],[3,'Исполнитель'],[6,'Наблюдатель'],[7,'Администратор']].map(([v,l])=>h('option',{value:v},l)));
    const recipient=h('select',{multiple:true,size:5},...(Array.isArray(users)?users:[]).filter(u=>u.is_active).map(u=>h('option',{value:u.id},personName(u)+' · '+u.id)));
    const groupSel=h('select',{multiple:true,size:4},...groups.map(g=>h('option',{value:g.id},g.name+' ('+g.member_ids.length+')')));\n    const tsel=h('select',{},h('option',{value:''},'Без шаблона'),...templates.map(x=>h('option',{value:x.id},x.name)));
    tsel.addEventListener('change',()=>{const t0=templates.find(x=>String(x.id)===tsel.value);if(t0){title.value=t0.title;body.value=t0.body;category.value=t0.category;priority.value=t0.priority;}});
    children.push(h('section',{class:'card'},h('h2',{},'Отправить уведомление'),
      h('label',{},'Шаблон',tsel),h('label',{},'Заголовок',title),h('label',{},'Сообщение',body),
      h('label',{},'Категория',category),h('label',{},'Приоритет',priority),
      h('label',{},'Получатели по ролям (можно несколько)',roles),
      h('label',{},'Отдельные сотрудники (можно несколько)',recipient),\n      h('label',{},'Именованные группы (можно несколько)',groupSel),
      h('label',{},h('span',{},'Включить запрос звука'),snd),
      h('button',{onclick:guard(async()=>{
        const recipient_ids=[...recipient.selectedOptions].map(x=>Number(x.value));
        const selectedRoles=[...roles.selectedOptions].map(x=>Number(x.value));
        if(!title.value.trim()||!body.value.trim()||(!recipient_ids.length&&!selectedRoles.length))throw Error('Заполните текст и выберите получателей');
        const result=await api('POST','/notifications',{title:title.value,body:body.value,category:category.value,priority:priority.value,sound:snd.checked,recipient_ids,roles:selectedRoles,group_ids});
        toast('Отправлено: '+result.sent);render();
      })},'Отправить'),
      h('hr'),h('h3',{},'Создать/обновить группу из выбранных сотрудников'),\n      ...(()=>{const gn=h('input',{placeholder:'Название группы'});return [gn,h('button',{onclick:guard(async()=>{if(!gn.value.trim()||!recipient.selectedOptions.length)throw Error('Укажите название и выберите участников');await api('PUT','/notifications/groups',{name:gn.value,member_ids:[...recipient.selectedOptions].map(x=>Number(x.value))});toast('Группа сохранена');render();})},'Сохранить группу')];})(),\n      h('hr'),h('h3',{},'Сохранить шаблон'),
      ...(()=>{const nm=h('input',{placeholder:'Название шаблона'});return [nm,h('button',{onclick:guard(async()=>{if(!nm.value.trim())throw Error('Введите название шаблона');await api('PUT','/notifications/templates',{name:nm.value,category:category.value,priority:priority.value,title:title.value,body:body.value});toast('Шаблон сохранён');render();})},'Сохранить текущий текст как шаблон')];})()
    ));
  }
  return h('div',{},...children);
}, []);
