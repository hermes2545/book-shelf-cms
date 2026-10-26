(() => {
  'use strict';
  const books = JSON.parse(document.querySelector('#books-data').textContent);
  const shelf = document.querySelector('#shelf');
  const search = document.querySelector('#search');
  const categories = document.querySelector('#categories');
  const count = document.querySelector('#count');
  const empty = document.querySelector('#empty');
  const reader = document.querySelector('#reader');
  const frame = document.querySelector('#reader-frame');
  let category = 'ทั้งหมด';

  const formatDate = value => new Intl.DateTimeFormat('th-TH', {day:'2-digit', month:'short', year:'numeric'}).format(new Date(`${value}T12:00:00`));

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function openReader(book) {
    document.querySelector('#reader-title').textContent = book.title;
    document.querySelector('#reader-meta').textContent = `${book.author} · ${book.category}`;
    document.querySelector('#reader-download').href = book.pdf;
    frame.src = `${book.pdf}#view=FitH`;
    reader.showModal();
  }

  function bookCard(book) {
    const article = make('article', 'book');
    const button = make('button', 'cover-button');
    button.type = 'button';
    button.setAttribute('aria-label', `เปิด ${book.title}`);
    const cover = make('div', 'cover');
    if (book.cover) {
      const image = document.createElement('img');
      image.src = book.cover;
      image.alt = `ปก ${book.title}`;
      image.loading = 'lazy';
      image.decoding = 'async';
      cover.append(image);
    } else {
      const fallback = make('div', 'cover-fallback');
      fallback.append(make('strong', '', book.title), make('span', '', book.author));
      cover.append(fallback);
    }
    button.append(cover);
    button.addEventListener('click', () => openReader(book));
    const info = make('div', 'book-info');
    info.append(make('h2', '', book.title), make('p', 'author', book.author));
    const meta = make('div', 'meta');
    meta.append(make('span', '', book.category), make('time', '', formatDate(book.published_at)));
    info.append(meta);
    article.append(button, info);
    return article;
  }

  function render() {
    const query = search.value.trim().toLocaleLowerCase('th');
    const visible = books.filter(book => {
      const inCategory = category === 'ทั้งหมด' || book.category === category;
      const haystack = `${book.title} ${book.author} ${book.category} ${book.description}`.toLocaleLowerCase('th');
      return inCategory && (!query || haystack.includes(query));
    });
    shelf.replaceChildren(...visible.map(bookCard));
    shelf.hidden = visible.length === 0;
    empty.hidden = visible.length !== 0;
    count.textContent = `${visible.length} รายการ`;
  }

  function renderCategories() {
    const names = ['ทั้งหมด', ...new Set(books.map(book => book.category))];
    categories.replaceChildren(...names.map(name => {
      const button = make('button', name === category ? 'active' : '', name);
      button.type = 'button';
      button.addEventListener('click', () => { category = name; renderCategories(); render(); });
      return button;
    }));
  }

  search.addEventListener('input', render);
  document.querySelector('#reader-close').addEventListener('click', () => reader.close());
  reader.addEventListener('close', () => { frame.src = 'about:blank'; });
  reader.addEventListener('click', event => { if (event.target === reader) reader.close(); });
  renderCategories();
  render();
})();
