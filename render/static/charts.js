/*
  CPI Health Dashboard — Chart bootstrapping

  Reads the global KPIS variable (injected by each template) and initializes
  every canvas on the page with the right Chart.js config.

  Port the chart definitions from /mnt/user-data/outputs/dashboard_overview.html
  into named factory functions here:
    - shareTrendChart(canvas, kpis)
    - marketTrendChart(canvas, kpis)
    - roiByMarketChart(canvas, kpis)
    - npByChannelChart(canvas, kpis)
    - channelMixChart(canvas, kpis)
    - funnelWaterfallChart(canvas, kpis)
    - weeklyTrendChart(canvas, kpis)
    - cpnpByMarketChart(canvas, kpis)
    - dailyPerformanceChart(canvas, kpis)
    - leadsToNpFunnelChart(canvas, kpis)

  Each function should:
    1. Pull the relevant slice from KPIS
    2. Apply the CPI brand color palette
    3. Use tabular figures via the font-variant-numeric set in CSS
    4. Stay restrained — no 3D, no shadows, no gradients beyond the hero card
*/

const BLUE = '#00477E';
const BLUE_2 = '#1a5a8e';
const STEEL = '#8FA8C0';
const MID = '#C5D8EC';
const LIGHT = '#E8F0F7';

Chart.defaults.font.family = "'Manrope', sans-serif";
Chart.defaults.color = '#404243';
Chart.defaults.borderColor = LIGHT;

// TODO: detect canvases by ID and initialize each with the right factory.
// Example:
//   const el = document.getElementById('shareTrend');
//   if (el) shareTrendChart(el, KPIS);
