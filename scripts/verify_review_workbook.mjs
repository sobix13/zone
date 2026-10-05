// Read-only visual/formula QA, with reversible input checks after rendering.
import fs from 'node:fs/promises';
import {FileBlob, SpreadsheetFile} from '@oai/artifact-tool';
const [path, outputDir] = process.argv.slice(2);
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
// The renderer's import guesses numeric-looking identifiers. Restore their exact
// strings from the same synthetic fixture; delivered OOXML already uses inlineStr.
const source=JSON.parse(await fs.readFile(path.replace('Synthetic-review-analysis.xlsx','synthetic-payload.json'),'utf8'));
const schema=JSON.parse(await fs.readFile(process.argv[5] || new URL('../assets/review-report-columns.json',import.meta.url),'utf8'));
const dataNames={Members:'members',Reviewers:'reviewers',Moderators:'moderators',Posts:'posts',Reviews:'reviews',Oversight:'evaluations'};
function letter(index){let s='';for(;index;index=Math.floor((index-1)/26))s=String.fromCharCode(65+(index-1)%26)+s;return s;}
for(const [name,columns] of Object.entries(schema)) {
 const rows=source[dataNames[name]], sheet=wb.worksheets.getItem(name);
 for(let n=0;n<columns.length;n++) if(columns[n][2]==='text' && columns[n][1].includes('id')) {
   if(!rows.length)continue;
   const r=sheet.getRange(`${letter(n+1)}6:${letter(n+1)}${rows.length+5}`);
   r.setNumberFormat('@');r.values=rows.map(row=>[row[columns[n][1]] == null ? null : "'"+row[columns[n][1]]]);
 }
}
if(source.weekly_goals.length) {
 const r=wb.worksheets.getItem('Calculator').getRange(`F6:F${source.weekly_goals.length+5}`);
 r.setNumberFormat('@');r.values=source.weekly_goals.map(row=>["'"+row.discord_id]);
}
await fs.mkdir(outputDir,{recursive:true});
wb.recalculate();
const calc=wb.worksheets.getItem('Calculator');
function expect(address,expected) {
  const value=calc.getRange(address).values[0][0];
  if (typeof expected === 'number' ? Math.abs(value-expected)>1e-8 : value!==expected) throw Error(`${address}: ${value} != ${expected}`);
}
expect('B30',payloadTotal());
function payloadTotal(){return Number(process.argv[4] || 176);}
const before=calc.getRange('B30').values[0][0];
calc.getRange('C10:C16').values=Array.from({length:7},()=>[0]);
wb.recalculate();
expect('C30',0); expect('B30',before);
calc.getRange('C10:C16').values=calc.getRange('B10:B16').values;
calc.getRange('C6').values=[[10]];
wb.recalculate();
expect('C32',500); expect('C25',0);
calc.getRange('C6').values=calc.getRange('B6').values;
wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:2500});
console.log(errors.ndjson);
const ranges={Overview:['A1:D24','A27:D44'],Calculator:['A1:J37'],Members:['A1:I8','J5:X8'],
  Reviewers:['A1:I8','J5:W8'],Moderators:['A1:K8'],Posts:['A1:H8','I5:L8'],Reviews:['A1:I8'],Oversight:['A1:H8','I5:M8']};
for (const [sheetName,views] of Object.entries(ranges)) {
  for (let i=0;i<views.length;i++) {
    const blob=await wb.render({sheetName,range:views[i],scale:1,format:'png'});
    await fs.writeFile(`${outputDir}/${sheetName.toLowerCase()}-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));
  }
}
console.log((await wb.inspect({kind:'table',range:'Calculator!A24:C34',include:'values,formulas',tableMaxRows:11,tableMaxCols:3,maxChars:2500})).ndjson);
console.log('Formula recalculation and zero-reward boundaries verified. No verification edits were exported.');
