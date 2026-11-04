/**
 * Boot: mount the desktop attention lane (NHI-03/04) once, for every route.
 * It shows the Notification Director's slot when the desktop is its surface;
 * nothing here switches routes or takes focus.
 */
import { mountAttentionLane } from '../components/attention-lane.js';

function mount() {
  window.OmniAttention = mountAttentionLane();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mount);
} else {
  mount();
}
