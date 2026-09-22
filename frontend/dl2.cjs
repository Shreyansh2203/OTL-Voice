const fs = require('fs'); const urls = [
'/_next/static/chunks/51685-a089ad7310a4bbb6.js',
'/_next/static/chunks/9732-e6d2400cbfe1dedb.js',
'/_next/static/chunks/36824-310a3df1eabb1407.js',
'/_next/static/chunks/a3cd4a83-450fbe72b6fb17c9.js',
'/_next/static/chunks/21784-510d3b4b4b2106c8.js',
'/_next/static/chunks/7790-8b8bf7e1f987c997.js',
'/_next/static/chunks/b536a0f1-8bd6b7fb13500681.js',
'/_next/static/chunks/bd904a5c-6a196b8f06c2aa77.js',
'/_next/static/chunks/96781-fdac6385d32d27c3.js'
]; Promise.all(urls.map(u => fetch('https://pro.reactbits.dev' + u).then(r=>r.text()).then(t => { if(t.includes('Tunnel')) { console.log('FOUND Tunnel IN', u); fs.writeFileSync('tunnel.js', t); } }))).then(()=>console.log('Done2'));
