// Spec §4 footprints; the minimum slot never shrinks to fit more controls.
export const footprints = Object.freeze({ S:[1,1], M:[2,1], L:[2,2], W:[3,1], F:[3,2] });
export function packDeck(instances, { width, height, gap = 12, slotWidth = 200, slotHeight = 150 }, registry) {
  const columns = Math.max(1, Math.floor((Math.max(0,width) + gap)/(slotWidth + gap)));
  const rows = Math.max(1, Math.floor((Math.max(0,height) + gap)/(slotHeight + gap)));
  const exception = width < slotWidth || height < slotHeight;
  const pages = [];
  let cells, page;
  const occupiedPages=[];
  const newPage = () => { page = []; pages.push(page); cells = Array.from({length:rows}, () => Array(columns).fill(false)); occupiedPages.push(cells); };
  newPage();
  for (const instance of instances) {
    const descriptor = registry.get(instance.widgetId);
    if (!descriptor) throw new Error('Unknown widget in deck');
    let size = descriptor.allowedSizes.includes(instance.size) ? instance.size : descriptor.preferredSize;
    // A tall briefing on a three-column compact deck would displace useful
    // supporting facts. Its declared M form keeps those facts close by.
    if (size === 'L' && columns < 4 && descriptor.allowedSizes.includes('M')) size = 'M';
    if (footprints[size][0] > columns || footprints[size][1] > rows) {
      size = [...descriptor.allowedSizes].reverse().find(s => footprints[s][0] <= columns && footprints[s][1] <= rows) || 'launcher';
    }
    const [spanX,spanY] = size === 'launcher' ? [1,1] : footprints[size];
    const find = () => {
      for (let y=0;y<=rows-spanY;y++) for (let x=0;x<=columns-spanX;x++) {
        if (Array.from({length:spanY}, (_,dy) => Array.from({length:spanX}, (_,dx) => !cells[y+dy][x+dx]).every(Boolean)).every(Boolean)) return { x,y };
      }
      return null;
    };
    let cell=null;
    for(let index=0;index<pages.length;index++) {
      page=pages[index];cells=occupiedPages[index];cell=find();if(cell)break;
    }
    if (!cell) { newPage(); cell = find(); }
    for (let dy=0;dy<spanY;dy++) for (let dx=0;dx<spanX;dx++) cells[cell.y+dy][cell.x+dx] = true;
    page.push({ ...instance, size, column:cell.x+1, row:cell.y+1, spanX,spanY });
  }
  return { pages, columns, rows, exception };
}
