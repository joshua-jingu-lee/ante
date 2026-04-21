# GitHub 인증 스킬

> 이 저장소에서 GitHub CLI 쓰기 작업을 하기 전에 로컬 PAT를 로드하고 상태를 점검한다.

## 목적

- `gh pr create`
- `gh issue comment`
- `gh run rerun`
- `gh workflow run`

같은 GitHub CLI 작업 전에 인증 상태를 일관되게 맞춘다.

## 로컬 파일 위치

- 실제 토큰 파일: `.github/local/github.env`
- 예시 파일: `.github/local/github.env.example`

실제 토큰 파일은 `.gitignore`로 제외한다.

## 사전 조건

- 토큰은 fine-grained PAT 권장
- 권한 권장치:
  - `Contents`: `Read and write`
  - `Pull requests`: `Read and write`
  - `Issues`: `Read and write`
  - `Actions`: `Read and write` (수동 복구에 `gh run rerun` / `gh workflow run` 필요)

## 초기 설정

```bash
cp .github/local/github.env.example .github/local/github.env
```

`GH_TOKEN` 값을 실제 PAT로 바꾼다.

## 사용 절차

```bash
source .github/local/github.env
gh auth status
```

## 점검 규칙

1. `gh auth status`가 성공하면 그대로 진행한다.
2. 실패하면 `.github/local/github.env`가 존재하는지 확인한다.
3. 파일이 있으면 다시 `source .github/local/github.env` 후 `gh auth status`를 재실행한다.
4. 계속 실패하면 PAT 만료 또는 권한 부족으로 보고 토큰을 재발급한다.

## 보안 원칙

- 토큰 문자열을 문서, 커밋, 이슈, PR 코멘트에 직접 남기지 않는다.
- `config/secrets.env`와 혼용하지 않는다.
- 쓰기 권한이 필요한 저장소만 대상으로 최소 권한으로 발급한다.
