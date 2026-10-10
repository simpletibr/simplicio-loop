// Shared DOM helpers of the lazily loaded cost widgets and agent map. Every name from an event reaches the page as
// textContent or an attribute value, never as markup.

export function make(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([name, value]) => node.setAttribute(name, value));
  node.append(...children);
  return node;
}

// Keyed rows of sl-gate-badge: the rows are created once, then only their attributes change.
export function renderBadges(list, rows) {
  if (list.children.length !== rows.length) {
    list.replaceChildren(...rows.map(() => make('li', {}, document.createElement('sl-gate-badge'))));
  }
  rows.forEach((row, index) => {
    const li = list.children[index];
    li.setAttribute('data-key', row.key);
    li.firstElementChild.setAttribute('gate', row.label);
    li.firstElementChild.setAttribute('state', row.state);
    li.firstElementChild.setAttribute('reason', row.detail);
  });
}
