// Owner-controlled source baseline for v2 diff validation. Never derived from POST data.
const fs=require('fs'),path=require('path'),{JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..'),w=new JSDOM('<div id="app"></div><div id="toast"></div>',{url:'http://localhost/',runScripts:'outside-only'}).window;
for(const name of ['demo-data','semantic-model','semantic-data','app'])w.eval(fs.readFileSync(path.join(root,'dist',name+'.js'),'utf8'));
const output=JSON.stringify(w.DNAWorkbench.baselineSnapshot(),null,2)+'\n';if(process.argv.includes('--check'))require('assert').equal(fs.readFileSync(path.join(root,'dist','adapter-baseline.json'),'utf8'),output,'Server adapter baseline must equal domain source baseline');else fs.writeFileSync(path.join(root,'dist','adapter-baseline.json'),output);w.close();
