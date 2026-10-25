// Schedule the next refresh only after the previous one finishes.
export function createPoller(refresh, interval = 4000, onError = () => {}) {
  let timer;
  let running = false;
  let enabled = false;
  let refreshAgain = false;

  async function tick() {
    if (!enabled || running) return;
    running = true;
    refreshAgain = false;
    try {
      await refresh();
    } catch (error) {
      onError(error);
    } finally {
      running = false;
      if (enabled) timer = setTimeout(tick, refreshAgain ? 0 : interval);
    }
  }

  return {
    start() {
      enabled = true;
      clearTimeout(timer);
      if (running) refreshAgain = true;
      else void tick();
    },
    stop() {
      enabled = false;
      refreshAgain = false;
      clearTimeout(timer);
    },
  };
}
