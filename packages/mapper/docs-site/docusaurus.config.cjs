const config = {
  title: 'Simplicio Mapper Docs',
  tagline: 'The docs hub for the scaffold, workflows, and agent operating model.',
  url: 'https://wesleysimplicio.github.io',
  baseUrl: '/simplicio-mapper/',
  organizationName: 'wesleysimplicio',
  projectName: 'simplicio-mapper',
  trailingSlash: false,
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },
  themes: [
    '@docusaurus/theme-mermaid',
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        indexDocs: true,
        indexBlog: false,
        indexPages: false,
        docsRouteBasePath: '/',
        docsDir: ['docs', 'versioned_docs'],
        explicitSearchResultPath: true,
        searchBarShortcut: true,
        searchBarShortcutHint: true,
      },
    ],
  ],
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      '@docusaurus/preset-classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: require.resolve('./sidebars.cjs'),
          showLastUpdateTime: true,
          versions: {
            current: {
              label: 'v0.x',
              banner: 'unreleased',
            },
          },
        },
        blog: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      },
    ],
  ],
  themeConfig: {
    image: 'assets/llm-project-mapper-hero.png',
    docs: {
      sidebar: {
        hideable: true,
        autoCollapseCategories: false,
      },
    },
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Simplicio Mapper',
      items: [
        {to: '/', label: 'Docs Home', position: 'left'},
        {to: '/quickstart/get-going', label: 'Quickstart', position: 'left'},
        {to: '/guide/private-overlay', label: 'Guide', position: 'left'},
        {to: '/yool-tuple-hamt', label: 'YOOL / tuple / HAMT', position: 'left'},
        {to: '/reference/cli-flags', label: 'Reference', position: 'left'},
        {type: 'docsVersionDropdown', position: 'right'},
        {
          href: 'https://github.com/wesleysimplicio/simplicio-mapper',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Quickstart', to: '/quickstart/get-going'},
            {label: 'Guide', to: '/guide/private-overlay'},
            {label: 'Reference', to: '/reference/init-handoff'},
          ],
        },
        {
          title: 'Concepts',
          items: [
            {label: 'Architecture Map', to: '/concepts/architecture-map'},
            {label: 'Domain Map', to: '/concepts/domain-map'},
            {label: 'Skills and Agents', to: '/concepts/skills-and-agents'},
            {label: 'YOOL / tuple / HAMT', to: '/yool-tuple-hamt'},
          ],
        },
        {
          title: 'Community',
          items: [
            {label: 'Showcase', to: '/community/showcase'},
            {label: 'Contributing', to: '/community/contributing'},
            {
              label: 'Source Repo',
              href: 'https://github.com/wesleysimplicio/simplicio-mapper',
            },
          ],
        },
      ],
      copyright: `Copyright ${new Date().getFullYear()} Wesley Simplicio`,
    },
    mermaid: {
      theme: {
        light: 'neutral',
        dark: 'forest',
      },
    },
  },
};

module.exports = config;
