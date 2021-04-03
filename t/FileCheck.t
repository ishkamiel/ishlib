package FileCheck;

use warnings;
use strict;

use Carp;
use Cwd;
use Data::Dumper;
use File::Basename;
use File::Find;
use File::Spec;
# use Test::More tests => 24;

my $dir       = File::Spec->catdir( cwd );
my $filecheck_dir = File::Spec->catdir( cwd, './t/filecheck' );
my @shells        = qw|sh bash zsh|;
my @files;

my @test_cases;

sub direct_run {
    my $t = shift;
    my $l = "$t->{env} $t->{shell} $t->{basename} $t->{args} -> $t->{output} -> $t->{exitval}";

    chdir $dir;
    my $cmd = qq|env -C "$dir" -i $t->{env} $t->{shell} $t->{fn} $t->{args} 2>&1|;
    my $output = qx|$cmd|;
    my $exitval = $? >> 8;    # TODO: Read up on why we need the shfit?

    # print Dumper($_);
    # print STDERR $cmd;
    # printf STDERR "exitval: $exitval\n";
    # printf STDERR "output: $output\n";

    is( $exitval, $t->{exitval},  "exitval_ok: $l" );
    like( $output, qr/$t->{output}/, "output_ok:  $l" );
    return;
}

sub main {
    prep_filecheck_cases();

    require Test::More;
    Test::More->import(tests => 2 * scalar(@test_cases));

    for (@test_cases) {
        direct_run($_);
    }

    return 1;
}

sub check_file {
    my $fn = shift;

    my @check_lines;

    open my $fh, "<", $fn or croak "Failed to open $fn";
    while (<$fh>) {
        s/^#\s*CHECK:\s+// and push @check_lines, $_;
    }
    close $fh;

    for (@check_lines) {
        m/^
            \s*( (?: (?:\w+=[^\s]*) (?:\s+\w+=[^\s]*)* )?)\s* \| # env
            \s*( \w+ )\s* \|                                     # shell
            \s*( (?: [^\|]*[^\s] )? )\s* \|                      # args
            \s*( (?: [^\|]*[^\s] )? )\s* \|                      # output
            \s*( (?: [^\|]*[^\s] )? )\s*                         # exitval
        $/x or die "Bad CHECK line: $_";

        push @test_cases,
          {
            fn      => $fn,
            basename => basename($fn),
            env     => $1,
            shell   => $2,
            args    => $3,
            output  => $4,
            exitval => $5
          };
    }

    return 1;
}

sub prep_filecheck_cases {
    find( sub { -f && m/\.(?:sh|bash)$/ && check_file $File::Find::name; },
        $filecheck_dir );
    return 1;
}

main();

1;
