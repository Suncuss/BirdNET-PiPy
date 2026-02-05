import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  // Base JS recommended rules
  js.configs.recommended,

  // Vue.js recommended rules
  ...pluginVue.configs['flat/recommended'],

  // Global settings
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
  },

  // Project-specific overrides
  {
    files: ['**/*.vue', '**/*.js'],
    rules: {
      // Relax some Vue rules for pragmatic development
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'warn',

      // Allow unused vars prefixed with underscore
      'no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_'
      }],
    },
  },

  // Ignore patterns
  {
    ignores: ['dist/', 'node_modules/', '*.config.js'],
  },
]
