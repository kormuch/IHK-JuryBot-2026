import asyncio, json, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from backend.repo_analyzer import analyze_repo
from backend.llm_service import LLMService
from backend.config import settings

async def test():
    analysis = await analyze_repo('C:/Users/kormu/projekte/IHK-JuryBot-2026/repos/team_2')
    total_chars = sum(len(v) for v in analysis['key_files'].values())
    print(f'Key files: {len(analysis["key_files"])} Dateien, {total_chars} chars (~{total_chars // 4} tokens)')
    print(f'LLM: {settings.LLM_PROVIDER} / {settings.LLM_MODEL}')
    llm = LLMService(settings)
    # Check prompt size after truncation
    prompt = llm._build_repo_prompt(analysis)
    print(f'Prompt-Laenge nach Kuerzung: {len(prompt)} chars (~{len(prompt)//4} tokens)')
    try:
        scores = await llm.evaluate_repo(analysis)
        print('SCORES OK:')
        print(json.dumps(scores, indent=2, ensure_ascii=False)[:2000])
    except Exception as e:
        import traceback; traceback.print_exc()

asyncio.run(test())
