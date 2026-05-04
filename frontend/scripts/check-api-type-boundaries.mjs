#!/usr/bin/env node

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { relative, sep } from 'node:path'

const root = new URL('..', import.meta.url).pathname.replace(/\/$/, '')
const srcRoot = `${root}/src`
const generatedType = `${srcRoot}/types/api.generated.ts`
const suffixPattern = /\b(?:interface|type)\s+([A-Z][A-Za-z0-9]*(?:Response|Request|Payload))\b/g
const generatedImportPattern = /from\s+['"][^'"]*types\/api\.generated['"]|from\s+['"][^'"]*api\.generated['"]/g
const clientCallPattern = /\bclient\.(get|post|put|patch|delete)\s*(?!<)\(/g
const unknownCastPattern = /\bas\s+unknown\s+as\b/g

const ignoredDirs = new Set(['node_modules', 'dist', '.vite-temp'])
const sourceExtensions = new Set(['.ts', '.tsx'])
const findings = []

function walk(dir) {
  const files = []
  for (const entry of readdirSync(dir)) {
    if (ignoredDirs.has(entry)) continue
    const path = `${dir}/${entry}`
    const stat = statSync(path)
    if (stat.isDirectory()) {
      files.push(...walk(path))
    } else if ([...sourceExtensions].some((ext) => path.endsWith(ext))) {
      files.push(path)
    }
  }
  return files
}

function rel(path) {
  return relative(root, path).split(sep).join('/')
}

function lineNumber(text, index) {
  return text.slice(0, index).split('\n').length
}

function domainFor(path) {
  const r = rel(path)
  if (r.startsWith('src/api/')) return 'api-adapter'
  if (r.startsWith('src/types/')) return 'types'
  if (r.startsWith('src/hooks/')) return 'hooks'
  if (r.startsWith('src/components/')) return 'components'
  if (r.startsWith('src/pages/')) return 'pages'
  return 'frontend'
}

function add(path, index, rule, message) {
  findings.push({
    file: rel(path),
    line: lineNumber(readFileSync(path, 'utf8'), index),
    rule,
    domain: domainFor(path),
    message,
  })
}

function isApiFile(path) {
  return rel(path).startsWith('src/api/')
}

function isGenerated(path) {
  return path === generatedType
}

function isAllowedUnknownCast(path, text, index) {
  if (!isApiFile(path)) return false
  const prefix = text.slice(0, index)
  const lastMapper = Math.max(
    prefix.lastIndexOf('function to'),
    prefix.lastIndexOf('const to')
  )
  const lastExportedApi = Math.max(
    prefix.lastIndexOf('export async function'),
    prefix.lastIndexOf('export function')
  )
  return lastMapper > lastExportedApi && /to[A-Z][A-Za-z0-9]*View/.test(prefix.slice(lastMapper, index))
}

for (const file of walk(srcRoot)) {
  const text = readFileSync(file, 'utf8')

  if (!isGenerated(file)) {
    for (const match of text.matchAll(suffixPattern)) {
      add(
        file,
        match.index,
        'manual-api-type-name',
        `Manual type '${match[1]}' looks like an API contract. Use View/Input/FormValues or generated types.`
      )
    }
  }

  if (!isApiFile(file) && !isGenerated(file)) {
    for (const match of text.matchAll(generatedImportPattern)) {
      add(
        file,
        match.index,
        'generated-import-outside-adapter',
        'Generated API types may only be imported by frontend/src/api/*.ts adapters.'
      )
    }
  }

  if (isApiFile(file)) {
    for (const match of text.matchAll(clientCallPattern)) {
      add(
        file,
        match.index,
        'client-call-without-generated-type',
        `client.${match[1]} call has no generated type parameter.`
      )
    }
  }

  for (const match of text.matchAll(unknownCastPattern)) {
    if (!isAllowedUnknownCast(file, text, match.index)) {
      add(
        file,
        match.index,
        'unknown-cast-outside-mapper',
        '`as unknown as` is only allowed inside api/*.ts toXxxView() mappers.'
      )
    }
  }
}

const byRule = findings.reduce((acc, finding) => {
  acc[finding.rule] = (acc[finding.rule] ?? 0) + 1
  return acc
}, {})

console.log('Frontend API type boundary report (report-only)')
console.log(`Scanned: ${rel(srcRoot)}`)
console.log(`Findings: ${findings.length}`)
for (const [rule, count] of Object.entries(byRule).sort()) {
  console.log(`- ${rule}: ${count}`)
}

if (findings.length > 0) {
  console.log('\nfile:line | rule | domain | message')
  for (const finding of findings) {
    console.log(
      `${finding.file}:${finding.line} | ${finding.rule} | ${finding.domain} | ${finding.message}`
    )
  }
}

console.log('\nResult: report-only, exit 0')
