import './style.css';
import Papa from 'papaparse';
import flatpickr from 'flatpickr';
import type { Instance as FlatpickrInstance } from 'flatpickr/dist/types/instance';
import 'flatpickr/dist/flatpickr.min.css';

// Data is copied into dashboard/public/data/ by scripts/sync_dashboard_data.py
// (run automatically by `python -m pipeline.run process`), so the built site
// in site/ is self-contained and works on GitHub Pages.
const eventsCsvUrl = './data/events.csv';
const statesCsvUrl = './data/states.csv';

interface EventData {
  event_id: string;
  state_code: string;
  state_name: string;
  city: string;
  category: string;
  title: string;
  summary: string;
  first_reported_date: string;
  primary_source_name: string;
  primary_source_url: string;
  source_count?: string;
}

interface StateData {
  state_code: string;
  state_name: string;
}

// Global font size management
let currentFontSize = 1;
const FONT_STEP = 0.1;
const MIN_FONT = 0.8;
const MAX_FONT = 1.6;

function updateFontSize() {
  document.body.style.setProperty('--content-font-size', `${currentFontSize}rem`);
}

document.getElementById('btn-font-dec')?.addEventListener('click', () => {
  if (currentFontSize > MIN_FONT) {
    currentFontSize -= FONT_STEP;
    updateFontSize();
  }
});

document.getElementById('btn-font-inc')?.addEventListener('click', () => {
  if (currentFontSize < MAX_FONT) {
    currentFontSize += FONT_STEP;
    updateFontSize();
  }
});

/** Build a Set of 'YYYY-MM-DD' strings for events matching the given state (or all states if empty) */
function buildDatesSet(events: EventData[], stateCode: string): Set<string> {
  const s = new Set<string>();
  for (const e of events) {
    if (e.first_reported_date && (!stateCode || e.state_code === stateCode)) {
      s.add(e.first_reported_date.split('T')[0]);
    }
  }
  return s;
}

async function init() {
  const [eventsRes, statesRes] = await Promise.all([
    fetch(eventsCsvUrl),
    fetch(statesCsvUrl)
  ]);

  if (!eventsRes.ok || !statesRes.ok) {
    document.getElementById('news-container')!.innerHTML =
      `<div class="loading">Failed to load data. Run <code>python scripts/sync_dashboard_data.py</code>, then <code>npm run dev</code>.</div>`;
    return;
  }

  const eventsText = await eventsRes.text();
  const statesText = await statesRes.text();

  const eventsParsed = Papa.parse<EventData>(eventsText, { header: true, skipEmptyLines: true });
  const statesParsed = Papa.parse<StateData>(statesText, { header: true, skipEmptyLines: true });

  const events = eventsParsed.data;
  const states = statesParsed.data;

  events.sort((a, b) => new Date(b.first_reported_date).getTime() - new Date(a.first_reported_date).getTime());

  const stateSelect = document.getElementById('state-select') as HTMLSelectElement;
  const dateSelect = document.getElementById('date-select') as HTMLInputElement;
  const newsContainer = document.getElementById('news-container') as HTMLDivElement;

  states.forEach(state => {
    const option = document.createElement('option');
    option.value = state.state_code;
    option.textContent = state.state_name;
    stateSelect.appendChild(option);
  });

  let selectedDateStr = '';

  // datesWithNews is rebuilt every time the state changes
  let datesWithNews = buildDatesSet(events, '');

  const renderNews = () => {
    const selectedState = stateSelect.value;

    let filtered = events;
    if (selectedState) {
      filtered = filtered.filter(e => e.state_code === selectedState);
    }
    if (selectedDateStr) {
      filtered = filtered.filter(e => e.first_reported_date && e.first_reported_date.startsWith(selectedDateStr));
    }

    newsContainer.innerHTML = '';

    if (filtered.length === 0) {
      newsContainer.innerHTML = '<div class="loading">No news found for the selected criteria.</div>';
      return;
    }

    filtered.slice(0, 10).forEach(item => {
      const el = document.createElement('div');
      el.className = 'news-item';
      el.addEventListener('click', (e) => {
        if ((e.target as HTMLElement).tagName === 'A') return;
        el.classList.toggle('expanded');
      });

      const titleEl = document.createElement('div');
      titleEl.className = 'news-title';
      titleEl.textContent = item.title;

      const metaEl = document.createElement('div');
      metaEl.className = 'news-meta';
      const dateStr = item.first_reported_date ? new Date(item.first_reported_date).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      }) : 'Unknown date';
      metaEl.textContent = `${dateStr} • ${item.state_name || item.state_code} • ${item.primary_source_name}`;

      const summaryEl = document.createElement('div');
      summaryEl.className = 'news-summary';
      summaryEl.textContent = item.summary;

      // Expanded view — no body text stored, so we display the full summary
      // clearly, category badge, and a link to the original source.
      const categoryLabel = item.category ? item.category.replace(/_/g, ' ') : '';
      const sourcesLabel = item.source_count && item.source_count !== '1'
        ? `Covered by ${item.source_count} outlets`
        : '';

      const fullArticleEl = document.createElement('div');
      fullArticleEl.className = 'news-article-full';
      fullArticleEl.innerHTML = `
        <p>${item.city ? `<strong>${item.city}</strong> — ` : ''}${item.summary}</p>
        <div class="article-badges">
          ${categoryLabel ? `<span class="badge">${categoryLabel}</span>` : ''}
          ${sourcesLabel ? `<span class="badge badge-sources">${sourcesLabel}</span>` : ''}
        </div>
        <p class="article-note">Full article text is not stored — click below to read the original.</p>
        <a class="article-link" href="${item.primary_source_url}" target="_blank" rel="noopener">
          Read on ${item.primary_source_name} &rarr;
        </a>
      `;

      el.appendChild(titleEl);
      el.appendChild(metaEl);
      el.appendChild(summaryEl);
      el.appendChild(fullArticleEl);

      newsContainer.appendChild(el);
    });
  };

  // Flatpickr instance — stored so we can call redraw() when state changes
  const fp: FlatpickrInstance = flatpickr(dateSelect, {
    dateFormat: 'Y-m-d',
    onChange(_selectedDates, dateStr) {
      selectedDateStr = dateStr;
      renderNews();
    },
    onDayCreate(_dObj, _dStr, _fp, dayElem) {
      const d = dayElem.dateObj;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      if (datesWithNews.has(key)) {
        dayElem.classList.add('has-news');
      }
    }
  }) as FlatpickrInstance;

  stateSelect.addEventListener('change', () => {
    // Rebuild the dots for the newly selected state, then force flatpickr to
    // redraw the current month so onDayCreate fires again with fresh dots.
    datesWithNews = buildDatesSet(events, stateSelect.value);
    if (fp && fp.redraw) fp.redraw();
    // Also clear the date filter — the old selected date may not exist in the new state
    selectedDateStr = '';
    fp.clear();
    renderNews();
  });

  renderNews();
}

init().catch(console.error);
