/**
 * Boot: mount the Galactic Intelligence briefing stack (GKI-04) once, for every
 * route. Briefings are suggestions the Commander may read or dismiss; nothing
 * here switches routes or takes focus.
 */
import { mountBriefings } from '../components/galactic-intelligence.js';

function mount() {
  window.OmniGalacticIntelligence = mountBriefings();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mount);
} else {
  mount();
}
