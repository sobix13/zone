// Authoring tool only. The VPS fills this template without Node or Office dependencies.
import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [schemaPath, outputDir] = process.argv.slice(2);
const schema = JSON.parse(await fs.readFile(schemaPath, 'utf8'));
await fs.mkdir(outputDir, { recursive: true });
const wb = Workbook.create();
const summary = wb.worksheets.add('Overview');
const calc = wb.worksheets.add('Calculator');
const sheets = {};
for (const name of Object.keys(schema)) sheets[name] = wb.worksheets.add(name);
function col(n) { let s = ''; for (;n;n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s; }
function heading(sheet, title, endCol) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${endCol}40`).format.font = { name: 'Arial', size: 10, color: '#29343B' };
  sheet.getRange(`A1:${endCol}40`).format.verticalAlignment = 'center';
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { name: 'Arial', size: 14, bold: true, color: '#79323D' };
  sheet.getRange(`A2:${endCol}2`).format.borders = { bottom: {style: 'thin', color: '#D8C2C6'} };
  sheet.getRange('A3').values = [['Template. No live records. UTC periods use an exclusive end.']];
  sheet.getRange('A3').format.font = {name:'Arial',size:10,italic:true,color:'#647179'};
  sheet.getRange(`A5:${endCol}5`).format = { fill: '#79323D', font: {name:'Arial',size:10,bold:true,color:'#FFFFFF'},
    horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:42,
    borders:{insideVertical:{style:'thin',color:'#FFFFFF'}} };
}
for (const [name, columns] of Object.entries(schema)) {
  const sheet = sheets[name], width = columns.length, end = col(width);
  heading(sheet, name === 'Oversight' ? 'Private moderation evidence' : name, end);
  sheet.getRange(`A5:${end}5`).values = [columns.map(c=>c[0])];
  sheet.getRange(`A6:${end}6`).values = [columns.map(c=>['text','date'].includes(c[2]) ? null : 0)];
  sheet.getRange(`A6:${end}6`).format.rowHeight=32;
  sheet.getRange(`A6:${end}6`).format.fill='#F8F5F5';
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(3);
  for (let i=0;i<width;i++) {
    const [label,key,type]=columns[i], letter=col(i+1), r=sheet.getRange(`${letter}5:${letter}6`);
    r.format.columnWidth = type === 'text' ? (key.includes('id') ? 36 : 24) : type === 'date' ? 23 : 19;
    sheet.getRange(`${letter}6`).setNumberFormat({text:'@',number:'0',decimal:'0.00',percent:'0.0%',date:'yyyy-mm-dd hh:mm'}[type]);
    if (type !== 'text') sheet.getRange(`${letter}6`).format.horizontalAlignment='right';
    if (['feedback','summary'].includes(key)) { r.format.columnWidth=70; sheet.getRange(`${letter}6`).format.wrapText=true; }
    if (key === 'checked_ids_json') { r.format.columnWidth=50; sheet.getRange(`${letter}6`).format.wrapText=true; }
    if (['tweet_link','twitter_comment'].includes(key)) r.format.columnWidth=44;
  }
}
summary.tabColor='#79323D'; calc.tabColor='#B6757F';
heading(summary,'Melee review analysis','D');
summary.getRange('A5:D5').values=[['Metric','Current window','Previous window','Definition']];
summary.getRange('A5:A34').format.columnWidth=40;
summary.getRange('B5:C34').format.columnWidth=20;
summary.getRange('D5:D44').format.columnWidth=88;
const metricRows=[
 ['Posts submitted',0,0,'Posts created during the window.'],
 ['Reviews submitted',0,0,'Review events recorded during the window.'],
 ['Current reviewer-role members',0,null,'Fresh current role inventory, not a historical roster.'],
 ['Current member-role members',0,null,'Optional member/content role.'],
 ['Active current-role reviewers',0,null,'At least one recorded review in the window.'],
 ['Mature review opportunities',0,null,'Assignment cohort with due date before the cutoff. Reassigned/removed excluded.'],
 ['Completed mature opportunities',0,null,'Cohort completions recorded before the cutoff.'],
 ['Mature completion rate',null,null,'Unavailable when there were no mature opportunities.'],
 ['Theoretical reviews per week',0,null,'All current reviewers multiplied by the configured weekly review limit.'],
 ['Measured review capacity/week',null,null,'Active current-role reviewers multiplied by limit and current-role mature completion rate.'],
 ['Required reviews per week',0,null,'Observed post arrivals multiplied by current required reviews/post.'],
 ['90th percentile response (hours)',null,null,'Assignment to completion, from observed completions.'],
 ['Volunteered reviewer slots/week',0,null,'Opted-in reviewer capacities.'],
 ['Volunteered member slots/week',0,null,'Opted-in member capacities. These are separate commitments.'],
 ['Regular MC paid',0,null,'Actual positive ledger entries. Not forecast MC.'],
 ['Golden MC paid',0,null,'Actual positive ledger entries.'],
 ['Assignment MC paid',0,null,'Actual positive ledger entries.'],
 ['Moderator evaluations',0,null,'Private reviewer and member evaluations.'],
 ['Full-sample evaluations',0,null,'Checked sample count reached the configured sample target.']
];
summary.getRange('A6:D24').values=metricRows;
summary.getRange('A6:D24').format.rowHeight=32;
summary.getRange('D6:D24').format.wrapText=true;
summary.getRange('B13').setNumberFormat('0.0%');
summary.getRange('B14:B22').setNumberFormat('0.00');
summary.getRange('A27').values=[['Evidence and scope']];
summary.getRange('A28').values=[['Recorded comment links are not independent proof of X engagement.']];
summary.getRange('A29').values=[['Current balances and role membership are as of report capture.']];
summary.getRange('A30').values=[['No opportunities and insufficient samples stay distinct from zero performance.']];
summary.getRange('A32:D32').values=[['Setup setting','Current','Suggested','Reason']];
summary.getRange('A32:D32').format={fill:'#79323D',font:{name:'Arial',bold:true,color:'#FFFFFF'},rowHeight:28};
summary.getRange('A33:D33').values=[['Workload',null,null,'Recommendations appear after sufficient observed assignments.']];
summary.getRange('D33:D40').format.wrapText=true;
summary.getRange('A33:D40').format.rowHeight=48;
summary.getRange('A42').values=[['Changes are proposals. Apply them only through the existing admin setup after review.']];

heading(calc,'Review setup calculator','J');
calc.getRange('A5:C5').values=[['Setting / estimate','Current rules','Proposed rules']];
calc.getRange('D5:E5').format.fill='#FFFFFF';
calc.getRange('F5:J5').values=[['Discord ID','Cycle week','Completed assignments','All comment links','Posts submitted']];
calc.getRange('A5:A36').format.columnWidth=40;
calc.getRange('B5:C36').format.columnWidth=19;
calc.getRange('D5:E40').format.columnWidth=3;
calc.getRange('F5:J40').format.columnWidth=23;
calc.getRange('F5:F40').format.columnWidth=36;
const settings=[['Reviews/reviewer/week',7,7],['Posts/member/week',5,5],['Required reviews/post',5,5],['Review window (days)',7,7],
 ['MC score 4 to below 6',1,1],['MC score 6 to below 8',3,3],['MC score 8 to 10',5,5],['Review-goal MC',2,2],
 ['All-comment-links bonus MC',1,1],['Submission-goal MC',2,2],['Showcase golden MC',3,3],['Showcase score threshold',8,8],
 ['Current reviewer-role members',0,0],['Active current-role reviewers',0,0],['Observed mature completion rate',null,null],['Window length (weeks)',2,2]];
calc.getRange('A6:C21').values=settings;
calc.getRange('C6:C17').format.fill='#FFF1CF';
calc.getRange('B6:C21').setNumberFormat('0.00');
calc.getRange('B20:C20').setNumberFormat('0.0%');
calc.getRange('F6:J6').values=[[null,null,0,0,0]];
calc.getRange('F6:G6').setNumberFormat('@');
calc.getRange('A23:C23').values=[['Estimated reward / workload','Current rules','Proposed rules']];
calc.getRange('A23:C23').format={fill:'#79323D',font:{name:'Arial',bold:true,color:'#FFFFFF'},rowHeight:32,wrapText:true};
calc.getRange('A24:A34').values=[['Post-score regular MC'],['Weekly review-goal MC'],['All-comment-links bonus MC'],['Weekly submission-goal MC'],
 ['Total estimated regular MC'],['Estimated golden MC'],['Total estimated MC'],['Review demand per week'],['Theoretical review capacity/week'],['Measured review capacity/week'],['Measured capacity shortfall/week']];
for (const c of ['B','C']) {
 const postRegular=c==='B'?'K':'I', postGold=c==='B'?'L':'J';
 const formulas=[`=SUM('Posts'!$${postRegular}$6:$${postRegular}$6)`,
 `=COUNTIFS($H$6:$H$6,">="&${c}6)*${c}13`,
 `=COUNTIFS($H$6:$H$6,">="&${c}6,$I$6:$I$6,1)*${c}14`,
 `=COUNTIFS($J$6:$J$6,">="&${c}7)*${c}15`,
 `=SUM(${c}24:${c}27)`,`=SUM('Posts'!$${postGold}$6:$${postGold}$6)`,`=SUM(${c}28:${c}29)`,
 `=COUNTA('Posts'!$A$6:$A$6)/${c}21*${c}8`,`${'='}${c}18*${c}6`,
 `=IF(${c}20="","",${c}19*${c}6*${c}20)`,`=IF(${c}33="","",MAX(0,${c}31-${c}33))`];
 calc.getRange(`${c}24:${c}34`).formulas=formulas.map(f=>[f]);
}
calc.getRange('A24:C34').format.rowHeight=30;
calc.getRange('B24:C34').setNumberFormat('0.00');
calc.getRange('A28:C30').format.font={name:'Arial',bold:true};
calc.getRange('A36').values=[['Amber cells are editable. Estimates use observed in-window cycle fragments, not historical payout reconstruction.']];
calc.getRange('A37').values=[['Proposed reviews/post is hypothetical. Saved requirements and deadlines never change. Review-window input does not rewrite observed due dates.']];
for (const row of [36,37]) {
  calc.getRange(`A${row}:C${row}`).merge();
  calc.getRange(`A${row}:C${row}`).format.wrapText=true;
  calc.getRange(`A${row}:C${row}`).format.rowHeight=44;
}
calc.dataValidations.add({range:'C6:C7',rule:{type:'whole',operator:'between',formula1:1,formula2:20}});
calc.dataValidations.add({range:'C8',rule:{type:'whole',operator:'between',formula1:1,formula2:10}});
calc.dataValidations.add({range:'C9',rule:{type:'whole',operator:'between',formula1:1,formula2:14}});
calc.dataValidations.add({range:'C10:C16',rule:{type:'decimal',operator:'between',formula1:0,formula2:1000}});
calc.dataValidations.add({range:'C17',rule:{type:'decimal',operator:'between',formula1:0,formula2:10}});
sheets.Members.getRange('N6').formulas=[['=SUM(K6:M6)']];
sheets.Reviewers.getRange('I6').formulas=[['=IF(G6=0,"",H6/G6)']];
for (const c of ['I','K']) {
 const s=c==='K'?'B':'C', target=c==='K'?'E6':`'Calculator'!$C$8`;
 sheets.Posts.getRange(c+'6').formulas=[[`=IF(F6<${target},0,IF(G6>=8,'Calculator'!$${s}$12,IF(G6>=6,'Calculator'!$${s}$11,IF(G6>=4,'Calculator'!$${s}$10,0))))`]];
}
for (const c of ['J','L']) {
 const s=c==='L'?'B':'C', target=c==='L'?'E6':`'Calculator'!$C$8`;
 sheets.Posts.getRange(c+'6').formulas=[[`=IF(F6<${target},0,IF(G6>='Calculator'!$${s}$17,'Calculator'!$${s}$16,0))`]];
}
wb.recalculate();
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:30},maxChars:1800})).ndjson);
for (const name of ['Overview','Calculator',...Object.keys(schema)]) {
 const preview=await wb.render({sheetName:name,range:name==='Overview'?'A1:D24':name==='Calculator'?'A1:J34':`A1:${col(Math.min(schema[name].length,9))}7`,scale:1,format:'png'});
 await fs.writeFile(`${outputDir}/${name.toLowerCase()}-preview.png`,new Uint8Array(await preview.arrayBuffer()));
}
console.log((await wb.inspect({kind:'table',range:'Calculator!A5:C34',include:'values,formulas',tableMaxRows:30,tableMaxCols:3,maxChars:3500})).ndjson);
await (await SpreadsheetFile.exportXlsx(wb)).save(`${outputDir}/review-support-template.xlsx`);
// Input-change check in memory after export. No changed test values enter the deliverable.
calc.getRange('C18').values=[[50]];
calc.getRange('C6').values=[[10]];
wb.recalculate();
const result=calc.getRange('C32').values[0][0];
if(result!==500) throw new Error(`Capacity recalculation failed: ${result}`);
console.log('Recalculation verified: 50 reviewers x 10 reviews = 500 theoretical slots/week.');
