package com.company.knowledge.search;

import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Public REST API for permission-aware enterprise search and question answering.
 */
@RestController
@RequestMapping("/api/v1")
public class SearchController {

    private final SearchService searchService;
    private final CurrentUserProvider currentUserProvider;

    public SearchController(SearchService searchService, CurrentUserProvider currentUserProvider) {
        this.searchService = searchService;
        this.currentUserProvider = currentUserProvider;
    }

    @PostMapping("/search")
    public ResponseEntity<SearchResponse> search(@Valid @RequestBody SearchRequest request) {
        UserContext user = currentUserProvider.getCurrentUser();
        SearchResponse response = searchService.search(request, user);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/ask")
    public ResponseEntity<AskResponse> ask(@Valid @RequestBody AskRequest request) {
        UserContext user = currentUserProvider.getCurrentUser();
        AskResponse response = searchService.ask(request, user);
        return ResponseEntity.ok(response);
    }
}
