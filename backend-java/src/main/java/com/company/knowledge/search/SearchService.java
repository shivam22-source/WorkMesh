package com.company.knowledge.search;

import com.company.knowledge.auth.UserContext;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;

/**
 * Service orchestrating permission-aware search and question answering.
 */
public interface SearchService {

    /**
     * Execute a search query with permission constraints derived from the user context.
     *
     * @param request search parameters
     * @param user authenticated user context
     * @return search response
     */
    SearchResponse search(SearchRequest request, UserContext user);

    /**
     * Ask a question and obtain an answer synthesized from permission-filtered evidence.
     *
     * @param request question request
     * @param user authenticated user context
     * @return answer with citations
     */
    AskResponse ask(AskRequest request, UserContext user);
}
