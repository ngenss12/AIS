#' Get vessel track from API and convert response to tibble
#'
#' @param vessel_id Character. A single GFW `vesselId`, obtained via [gfw_vessel_info()].
#' @param start_date Start of date range to search track, in `"YYYY-MM-DD"` format.
#' @param end_date End of date range to search track, in `"YYYY-MM-DD"` format.
#' @param key Character, API token. Defaults to [gfw_auth()].
#' @param quiet Boolean. Whether to suppress progress messages. Default is `FALSE`.
#' @param print_request Boolean. Whether to print the request URL, for debugging
#' purposes. Default is `FALSE`.
#'
#' @return A tibble with columns:
#' \describe{
#'   \item{`vessel_id`}{GFW vessel ID}
#'   \item{`timestamp`}{POSIXct timestamp in UTC}
#'   \item{`lon`}{Longitude}
#'   \item{`lat`}{Latitude}
#'   \item{`speed`}{Speed in knots}
#'   \item{`course`}{Course in degrees}
#' }
#'
#' @details
#' The function calls the `GET /vessels/{vesselId}/tracks` endpoint from the
#' Global Fishing Watch API v3, which returns AIS position data as a GeoJSON
#' feature. Each row in the resulting tibble corresponds to one AIS position
#' broadcast received from the vessel.
#'
#' The `vessel_id` must be a GFW internal ID (not MMSI or IMO). Use
#' [gfw_vessel_info()] to retrieve the correct `vesselId` from
#' `$selfReportedInfo$vesselId`.
#'
#' @examples
#' \dontrun{
#' library(gfwr)
#'
#' # Step 1: get the GFW vesselId first
#' vessel <- gfw_vessel_info(query = 224224000, search_type = "search")
#' vessel_id <- vessel$selfReportedInfo$vesselId[1]
#'
#' # Step 2: get the track
#' track <- gfw_vessel_track(
#'   vessel_id  = vessel_id,
#'   start_date = "2023-01-01",
#'   end_date   = "2023-03-31"
#' )
#'
#' # Step 3: plot
#' library(ggplot2)
#' ggplot(track, aes(x = lon, y = lat)) +
#'   geom_path(color = "red") +
#'   coord_quickmap()
#' }
#'
#' @importFrom httr2 request
#' @importFrom httr2 req_url_path_append
#' @importFrom httr2 req_url_query
#' @importFrom httr2 req_headers
#' @importFrom httr2 req_user_agent
#' @importFrom httr2 req_perform
#' @importFrom httr2 resp_body_json
#' @importFrom tibble tibble
#' @importFrom purrr pluck
#' @export
gfw_vessel_track <- function(vessel_id,
                             start_date,
                             end_date,
                             key = gfw_auth(),
                             quiet = FALSE,
                             print_request = FALSE) {

  if (missing(vessel_id) || is.null(vessel_id) || length(vessel_id) != 1) {
    stop("'vessel_id' must be a single character string. Use gfw_vessel_info() to obtain the vesselId.")
  }
  if (missing(start_date) || missing(end_date)) {
    stop("'start_date' and 'end_date' are required, in 'YYYY-MM-DD' format.")
  }

  endpoint <- httr2::request("https://gateway.api.globalfishingwatch.org/v3/") %>%
    httr2::req_url_path_append("vessels", vessel_id, "tracks") %>%
    httr2::req_url_query(
      `datasets[0]` = "public-global-vessel-track:latest",
      `start-date`  = start_date,
      `end-date`    = end_date
    ) %>%
    httr2::req_headers(Authorization = paste("Bearer", key)) %>%
    httr2::req_user_agent(gfw_user_agent())

  if (print_request) print(endpoint)

  response <- endpoint %>%
    httr2::req_perform() %>%
    httr2::resp_body_json()

  coords <- purrr::pluck(response, "geometry", "coordinates")

  if (is.null(coords) || length(coords) == 0) {
    if (!quiet) message("No track data found for this vessel in the given date range.")
    return(tibble::tibble(
      vessel_id = character(),
      timestamp = as.POSIXct(character()),
      lon       = numeric(),
      lat       = numeric(),
      speed     = numeric(),
      course    = numeric()
    ))
  }

  times  <- purrr::pluck(response, "properties", "coordinateProperties", "times")
  speeds <- purrr::pluck(response, "properties", "coordinateProperties", "speed")
  course <- purrr::pluck(response, "properties", "coordinateProperties", "course")

  n <- length(coords)

  track <- tibble::tibble(
    vessel_id = vessel_id,
    timestamp = as.POSIXct(
      unlist(times) / 1000,
      origin = "1970-01-01",
      tz = "UTC"
    ),
    lon   = vapply(coords, `[[`, numeric(1), 1),
    lat   = vapply(coords, `[[`, numeric(1), 2),
    speed  = if (!is.null(speeds)) unlist(speeds) else rep(NA_real_, n),
    course = if (!is.null(course)) unlist(course) else rep(NA_real_, n)
  )

  if (!quiet) message(paste(nrow(track), "positions returned for vessel", vessel_id))

  return(track)
}
