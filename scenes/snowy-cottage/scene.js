// The scene is data: scene.json (written by tools/analyze_plate.py, tuned by hand). Keys: src/library/autoscene.js.
import spec from './scene.json' with { type: 'json' };
import { autoScene } from '../../src/library/autoscene.js';

export default autoScene(spec);
