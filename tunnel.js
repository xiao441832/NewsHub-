const cf = require('cloudflared');
const tunnel = cf.tunnel({ url: 'http://localhost:8080' });
tunnel.on('url', u => { console.log('URL:', u); });
tunnel.on('stderr', d => process.stderr.write(d));
tunnel.on('exit', c => { console.log('EXIT:', c); });
