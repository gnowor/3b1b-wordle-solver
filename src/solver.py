import numpy as np
from tqdm import tqdm

from src.entropy import (
    entropy_of_distributions,
    get_bucket_counts,
    get_entropies,
    get_pattern_distributions,
)
from src.pattern import get_pattern, get_possible_words, get_word_buckets
from src.prior import get_word_list

# Solvers


def get_weights(words, priors):
    frequencies = np.array([priors[word] for word in words])
    total = frequencies.sum()
    if total == 0:
        return np.zeros(frequencies.shape)
    return frequencies / total


def entropy_to_expected_score(ent):
    """
    Based on a regression associating entropies with typical scores
    from that point forward in simulated games, this function returns
    what the expected number of guesses required will be in a game where
    there's a given amount of entropy in the remaining possibilities.
    """
    # Assuming you can definitely get it in the next guess,
    # this is the expected score
    min_score = 2 ** (-ent) + 2 * (1 - 2 ** (-ent))

    # To account for the likely uncertainty after the next guess,
    # and knowing that entropy of 11.5 bits seems to have average
    # score of 3.5, we add a line to account
    # we add a line which connects (0, 0) to (3.5, 11.5)
    return min_score + 1.5 * ent / 11.5


def get_expected_scores(
    allowed_words,
    possible_words,
    priors,
    game_name,
    look_two_ahead=False,
    n_top_candidates_for_two_step=25,
):
    
    if len(possible_words) == 0:
        raise ValueError("No possible words available for guessing.")
    # Currently entropy of distribution
    weights = get_weights(possible_words, priors)
    h0 = entropy_of_distributions(weights)
    h1s = get_entropies(allowed_words, possible_words, weights, game_name)

    word_to_weight = dict(zip(possible_words, weights, strict=True))
    probs = np.array([word_to_weight.get(w, 0) for w in allowed_words])
    # If this guess is the true answer, score is 1. Otherwise, it's 1 plus
    # the expected number of guesses it will take after getting the corresponding
    # amount of information.
    expected_scores = probs + (1 - probs) * (1 + entropy_to_expected_score(h0 - h1s))

    if not look_two_ahead:
        return expected_scores

    # For the top candidates, refine the score by looking two steps out
    # This is currently quite slow, and could be optimized to be faster.
    # But why?
    sorted_indices = np.argsort(expected_scores)
    allowed_second_guesses = get_word_list(game_name)
    expected_scores += 1  # Push up the rest
    for i in tqdm(
        sorted_indices[:n_top_candidates_for_two_step],
        leave=False,
    ):
        guess = allowed_words[i]
        h1 = h1s[i]
        dist = get_pattern_distributions([guess], possible_words, weights, game_name)[0]
        buckets = get_word_buckets(guess, possible_words, game_name)
        second_guesses = [
            optimal_guess(
                allowed_second_guesses,
                bucket,
                priors,
                game_name=game_name,
                look_two_ahead=False,
            )
            for bucket in buckets
        ]
        h2s = [
            get_entropies([guess2], bucket, get_weights(bucket, priors), game_name)[0]
            for guess2, bucket in zip(second_guesses, buckets, strict=True)
        ]

        prob = word_to_weight.get(guess, 0)
        expected_scores[i] = sum(
            (
                # 1 times Probability guess1 is correct
                1 * prob,
                # 2 times probability guess2 is correct
                2
                * (1 - prob)
                * sum(
                    p * word_to_weight.get(g2, 0)
                    for p, g2 in zip(dist, second_guesses, strict=True)
                ),
                # 2 plus expected score two steps from now
                (1 - prob)
                * (
                    2
                    + sum(
                        p
                        * (1 - word_to_weight.get(g2, 0))
                        * entropy_to_expected_score(h0 - h1 - H2)
                        for p, g2, H2 in zip(dist, second_guesses, h2s, strict=True)
                    )
                ),
            ),
        )
    return expected_scores


def get_score_lower_bounds(allowed_words, possible_words, game_name):
    """
    Assuming a uniform distribution on how likely each element
    of possible_words is, this gives a lower bound on the
    possible score for each word in allowed_words
    """
    if len(possible_words) == 0:
        raise ValueError("No possible words available for guessing.")
    bucket_counts = get_bucket_counts(allowed_words, possible_words, game_name)
    n = len(possible_words)
    # Probabilities of getting it in 1
    p1s = np.array([w in possible_words for w in allowed_words]) / n
    # Probabilities of getting it in 2
    p2s = bucket_counts / n - p1s
    # Otherwise, assume it's gotten in 3 (which is optimistic)
    p3s = 1 - bucket_counts / n
    return p1s + 2 * p2s + 3 * p3s


def optimal_guess(
    allowed_words,
    possible_words,
    priors,
    game_name,
    look_two_ahead=False,
    optimize_for_uniform_distribution=False,
    purely_maximize_information=False,
):
    if purely_maximize_information:
        if len(possible_words) == 1:
            return possible_words[0]
        weights = get_weights(possible_words, priors)
        entropies = get_entropies(allowed_words, possible_words, weights, game_name)
        return allowed_words[np.argmax(entropies)]

    if len(allowed_words) == 0:
        raise ValueError("No allowed words available.")
        
    if optimize_for_uniform_distribution:
        expected_scores = get_score_lower_bounds(
            allowed_words,
            possible_words,
            game_name,
        )
    else:
        expected_scores = get_expected_scores(
            allowed_words,
            possible_words,
            priors,
            game_name=game_name,
            look_two_ahead=look_two_ahead,
        )
    
    if len(expected_scores) == 0:
        raise ValueError("No expected scores calculated for argmin.")

    return allowed_words[np.argmin(expected_scores)]



def brute_force_optimal_guess(
    all_words,
    possible_words,
    priors,
    game_name,
    n_top_picks=10,
    display_progress=False,
):
    if len(possible_words) == 0:
        # Doesn't matter what to return in this case, so just default to first word in list.
        return all_words[0]
    # For the suggestions with the top expected scores, just
    # actually play the game out from this point to see what
    # their actual scores are, and minimize.
    expected_scores = get_score_lower_bounds(all_words, possible_words, game_name)
    top_choices = [all_words[i] for i in np.argsort(expected_scores)[:n_top_picks]]
    true_average_scores = []
    if display_progress:
        iterable = tqdm(
            top_choices,
            desc=f"Possibilities: {len(possible_words)}",
            leave=False,
        )
    else:
        iterable = top_choices

    for next_guess in iterable:
        scores = []
        for answer in possible_words:
            score = 1
            possibilities = list(possible_words)
            guess = next_guess
            while guess != answer:
                possibilities = get_possible_words(
                    guess,
                    get_pattern(guess, answer, game_name),
                    possibilities,
                    game_name,
                )
                # Make recursive? If so, we'd want to keep track of
                # the next_guess map and pass it down in the recursive
                # sub-calls
                guess = optimal_guess(
                    all_words,
                    possibilities,
                    priors,
                    game_name=game_name,
                    optimize_for_uniform_distribution=True,
                )
                score += 1
            scores.append(score)
        true_average_scores.append(np.mean(scores))
    return top_choices[np.argmin(true_average_scores)]
