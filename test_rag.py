"""
test_rag.py - Automated End-to-End Tests for Smart Energy AI RAG Service
Tests 5 core requirements:
1. Direct knowledge question
2. Multi-source question
3. Irrelevant question
4. Retrieval relevance
5. Grounding
"""

import sys
import rag_service

def run_tests():
    print("=" * 60)
    print("STARTING RAG FUNCTIONAL SUITE")
    print("=" * 60)

    # Status check
    status = rag_service.rag_service.status()
    print(f"RAG Service Status: Available={status['available']}, Chunks={status['chunks']}, Docs={len(status['documents'])}")
    assert status['available'], "RAG Service should be available"
    assert status['chunks'] > 0, "RAG Service should have indexed chunks"

    passed_count = 0
    total_count = 5

    # --------------------------------------------------
    # TEST 1: Direct Knowledge Question
    # --------------------------------------------------
    print("\n--- TEST 1: Direct Knowledge Question ---")
    q1 = "What are the rules for human approval before executing energy actions?"
    res1 = rag_service.rag_service.query(q1)
    print(f"Question: {q1}")
    print(f"Mode: {res1['mode']}")
    print(f"Answer: {res1['answer']}")
    print(f"Top Source: {res1['sources'][0]['document']} -> {res1['sources'][0]['section']}")
    
    t1_pass = res1['mode'] != "no_match" and len(res1['sources']) > 0 and "approval" in res1['answer'].lower()
    print(f"TEST 1 RESULT: {'PASS' if t1_pass else 'FAIL'}")
    if t1_pass: passed_count += 1

    # --------------------------------------------------
    # TEST 2: Multi-Source Question
    # --------------------------------------------------
    print("\n--- TEST 2: Multi-Source Question ---")
    q2 = "How do battery storage and solar PV generation work together during peak demand?"
    res2 = rag_service.rag_service.query(q2)
    print(f"Question: {q2}")
    print(f"Mode: {res2['mode']}")
    print(f"Answer: {res2['answer']}")
    docs2 = set(s['document'] for s in res2['sources'])
    print(f"Retrieved Documents: {docs2}")
    
    t2_pass = len(docs2) >= 2 and len(res2['sources']) > 1
    print(f"TEST 2 RESULT: {'PASS' if t2_pass else 'FAIL'}")
    if t2_pass: passed_count += 1

    # --------------------------------------------------
    # TEST 3: Irrelevant Question
    # --------------------------------------------------
    print("\n--- TEST 3: Irrelevant Question ---")
    q3 = "What is the capital city of France and who won the 1998 World Cup?"
    res3 = rag_service.rag_service.query(q3)
    print(f"Question: {q3}")
    print(f"Mode: {res3['mode']}")
    print(f"Answer: {res3['answer']}")
    print(f"Sources Count: {len(res3['sources'])}")
    
    t3_pass = res3['mode'] == "no_match" and len(res3['sources']) == 0
    print(f"TEST 3 RESULT: {'PASS' if t3_pass else 'FAIL'}")
    if t3_pass: passed_count += 1

    # --------------------------------------------------
    # TEST 4: Retrieval Relevance
    # --------------------------------------------------
    print("\n--- TEST 4: Retrieval Relevance ---")
    q4 = "Why does reducing HVAC load lower total building energy demand?"
    res4 = rag_service.rag_service.query(q4)
    print(f"Question: {q4}")
    top_score = res4['sources'][0]['score'] if res4['sources'] else 0
    top_section = res4['sources'][0]['section'] if res4['sources'] else ""
    print(f"Top Score: {top_score}, Section: {top_section}")
    
    t4_pass = top_score >= rag_service.MIN_SCORE and "HVAC" in top_section or "hvac" in res4['sources'][0]['document']
    print(f"TEST 4 RESULT: {'PASS' if t4_pass else 'FAIL'}")
    if t4_pass: passed_count += 1

    # --------------------------------------------------
    # TEST 5: Grounding
    # --------------------------------------------------
    print("\n--- TEST 5: Grounding ---")
    print(f"Answer checked for inline citations [1], [2], etc.: {res1['answer']}")
    grounded = "[" in res1['answer'] and "]" in res1['answer'] and all("excerpt" in s and "document" in s for s in res1['sources'])
    print(f"Sources correctly mapped: {grounded}")
    
    t5_pass = grounded
    print(f"TEST 5 RESULT: {'PASS' if t5_pass else 'FAIL'}")
    if t5_pass: passed_count += 1

    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed_count}/{total_count} TESTS PASSED")
    print("=" * 60)

    if passed_count == total_count:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
