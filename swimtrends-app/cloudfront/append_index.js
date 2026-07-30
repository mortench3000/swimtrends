// CloudFront viewer-request function: append /index.html to extensionless paths.
//
// The origin is an S3 REST endpoint behind OAC, which — unlike an S3 *website*
// endpoint — has no directory index document, and DefaultRootObject applies only
// to "/". So /DM-L/12486 looks for the key "DM-L/12486", misses, and falls
// through to the 403/404 -> /index.html error response, serving the generic SPA
// shell instead of the prerendered page. That failure is silent, hence the test
// in tests/unit/test_web_stack.py.
//
// Paths that keep an extension are real objects (/robots.txt, /sitemap.xml,
// /assets/*, /data/*.json) and must pass through untouched.
//
// ES5 only: the CloudFront Functions runtime is not a full modern JS engine.
function handler(event) {
  var uri = event.request.uri;
  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last === '') {
    event.request.uri = uri + 'index.html';
  } else if (last.indexOf('.') === -1) {
    event.request.uri = uri + '/index.html';
  }
  return event.request;
}
