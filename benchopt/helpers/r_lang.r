##' Functions used to check RPy2 overhead in benchopt
##'
##' @title Functions to measure RPy2 overhead
##' @author Thomas Moreau
##' @export

RETURN = rep(0, 100000)

empty_run <- function(n, ...) {
    result = list(
        beta = RETURN,
        a0 = 0
    )
    return(result)
}
