// Python lives only in this worker. No diagram can execute bash in the page.
import {loadPyodide} from '../vendor/pyodide/pyodide.mjs';
const ready = (async () => {
  const py = await loadPyodide({indexURL: new URL('../vendor/pyodide/', import.meta.url).href});
  const response = await fetch(new URL('../gripeline.py', import.meta.url));
  if (!response.ok) throw Error('Unable to load gripeline.py');
  const compiler=await response.text();
  py.FS.writeFile('/gripeline.py', compiler);
  self.postMessage({type:'compiler',source:compiler});
  await py.runPythonAsync('import sys; sys.path.insert(0, "/"); from gripeline import gripeline_api; import json');
  return py;
})();
self.onmessage = async ({data: {id, src, lang, portable}}) => {
  try {
    const py = await ready;
    py.globals.set('source_text', src); py.globals.set('source_lang', lang || null); py.globals.set('portable_advice', portable);
    const result = JSON.parse(py.runPython('json.dumps(gripeline_api(source_text, source_lang, portable=portable_advice))'));
    self.postMessage({id, result});
  } catch (error) { self.postMessage({id, error: String(error)}); }
};
